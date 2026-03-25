import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Team
from app.services.settings import settings_service
from app.services.team import team_service

logger = logging.getLogger(__name__)


class AutoStatusRefreshService:
    """Background task for periodically refreshing team status."""
    DEFAULT_CONCURRENCY = 3
    MAX_CONCURRENCY = 10

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._run_lock = asyncio.Lock()

    @staticmethod
    def _parse_schedule_time(value: str) -> Tuple[int, int]:
        try:
            hour_str, minute_str = str(value).strip().split(":", 1)
            hour = int(hour_str)
            minute = int(minute_str)
        except (AttributeError, TypeError, ValueError):
            return 3, 0

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return 3, 0

        return hour, minute

    @classmethod
    def _get_current_slot(
        cls,
        now: datetime,
        start_time: str,
        interval_hours: int,
    ) -> datetime:
        hour, minute = cls._parse_schedule_time(start_time)
        interval_hours = max(1, min(interval_hours, 24))

        first_slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < first_slot:
            first_slot -= timedelta(days=1)

        elapsed_seconds = max(0, int((now - first_slot).total_seconds()))
        interval_seconds = interval_hours * 3600
        slot_offset = elapsed_seconds // interval_seconds
        return first_slot + timedelta(seconds=slot_offset * interval_seconds)

    @staticmethod
    async def _load_config(db_session) -> Dict[str, Any]:
        return {
            "enabled": await settings_service.get_bool_setting(
                db_session,
                "auto_status_refresh_enabled",
                False,
            ),
            "start_time": await settings_service.get_setting(
                db_session,
                "auto_status_refresh_start_time",
                "03:00",
            ),
            "interval_hours": max(
                1,
                min(
                    24,
                    await settings_service.get_int_setting(
                        db_session,
                        "auto_status_refresh_interval_hours",
                        24,
                    ),
                ),
            ),
            "last_slot": await settings_service.get_setting(
                db_session,
                "auto_status_refresh_last_slot",
                "",
            ),
        }

    @staticmethod
    async def _mark_last_slot(slot_value: str) -> None:
        async with AsyncSessionLocal() as db_session:
            await settings_service.update_setting(
                db_session,
                "auto_status_refresh_last_slot",
                slot_value,
            )

    @staticmethod
    async def _get_team_ids(db_session) -> List[int]:
        status_priority = {
            "error": 0,
            "expired": 1,
            "full": 2,
            "active": 3,
        }
        stmt = select(Team.id, Team.status, Team.last_sync).where(Team.status != "banned")
        result = await db_session.execute(stmt)
        rows = result.all()

        candidates = []
        for team_id, status, last_sync in rows:
            normalized_status = str(status or "").strip().lower()
            candidates.append(
                (
                    status_priority.get(normalized_status, 4),
                    last_sync is not None,
                    last_sync or datetime.min,
                    team_id,
                )
            )

        candidates.sort()
        return [team_id for _, _, _, team_id in candidates]

    async def _sync_single_team(self, team_id: int) -> Dict[str, Any]:
        try:
            async with AsyncSessionLocal() as db_session:
                result = await team_service.sync_team_info(team_id, db_session)
        except Exception as exc:
            logger.error(f"账号状态自动刷新 Team {team_id} 执行异常: {exc}")
            return {
                "team_id": team_id,
                "success": False,
                "message": None,
                "error": str(exc) or "刷新异常",
            }

        return {
            "team_id": team_id,
            "success": result.get("success", False),
            "message": result.get("message"),
            "error": result.get("error"),
        }

    async def _run_team_sync(
        self,
        team_ids: List[int],
        *,
        concurrency: int,
    ) -> List[Dict[str, Any]]:
        semaphore = asyncio.Semaphore(max(1, min(concurrency, self.MAX_CONCURRENCY)))

        async def worker(team_id: int) -> Dict[str, Any]:
            async with semaphore:
                return await self._sync_single_team(team_id)

        return await asyncio.gather(*(worker(team_id) for team_id in team_ids))

    async def start(self) -> None:
        if self._task and not self._task.done():
            return

        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("账号状态自动刷新后台任务已启动")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("账号状态自动刷新后台任务已停止")

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                async with AsyncSessionLocal() as db_session:
                    config = await self._load_config(db_session)

                if config["enabled"]:
                    tz = pytz.timezone(settings.timezone)
                    now = datetime.now(tz)
                    current_slot = self._get_current_slot(
                        now,
                        config["start_time"],
                        config["interval_hours"],
                    )
                    slot_key = current_slot.isoformat()

                    if slot_key != config["last_slot"]:
                        await self.process_once(slot_key)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"账号状态自动刷新巡检异常: {exc}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                continue

    async def process_once(self, slot_key: Optional[str] = None) -> Dict[str, Any]:
        async with self._run_lock:
            async with AsyncSessionLocal() as db_session:
                team_ids = await self._get_team_ids(db_session)

            concurrency = self.DEFAULT_CONCURRENCY

            summary = {
                "success": True,
                "processed": 0,
                "succeeded": 0,
                "failed": 0,
                "concurrency": concurrency,
                "details": [],
                "message": "",
            }

            results = await self._run_team_sync(team_ids, concurrency=concurrency)

            for detail in results:
                summary["processed"] += 1
                summary["details"].append(detail)

                if detail["success"]:
                    summary["succeeded"] += 1
                else:
                    summary["failed"] += 1

            summary["message"] = (
                f"账号状态自动刷新完成: 处理 {summary['processed']} 个账号, "
                f"成功 {summary['succeeded']} 个, 失败 {summary['failed']} 个"
            )
            logger.info(summary["message"])

            if slot_key:
                await self._mark_last_slot(slot_key)

            return summary


auto_status_refresh_service = AutoStatusRefreshService()
