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
        stmt = (
            select(Team.id)
            .where(Team.status != "banned")
            .order_by(Team.id.asc())
        )
        result = await db_session.execute(stmt)
        return list(result.scalars().all())

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

            summary = {
                "success": True,
                "processed": 0,
                "succeeded": 0,
                "failed": 0,
                "details": [],
                "message": "",
            }

            for team_id in team_ids:
                summary["processed"] += 1
                async with AsyncSessionLocal() as db_session:
                    result = await team_service.sync_team_info(team_id, db_session)

                detail = {
                    "team_id": team_id,
                    "success": result.get("success", False),
                    "message": result.get("message"),
                    "error": result.get("error"),
                }
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
