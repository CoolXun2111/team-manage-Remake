import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import RedemptionCode, RedemptionRecord, Team
from app.services.redeem_flow import redeem_flow_service
from app.services.settings import settings_service
from app.services.warranty import warranty_service

logger = logging.getLogger(__name__)


class AutoReinviteService:
    """失效母号自动补邀服务。"""
    ELIGIBLE_SOURCE_STATUSES = {"banned"}
    DEFAULT_START_TIME = "00:00"
    DEFAULT_INTERVAL_MINUTES = 5
    DEFAULT_BATCH_SIZE = 20
    DEFAULT_CONCURRENCY = 1

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._run_lock = asyncio.Lock()

    @staticmethod
    def _normalize_email(email: Optional[str]) -> str:
        return (email or "").strip().lower()

    @staticmethod
    def _parse_schedule_time(value: str) -> Tuple[int, int]:
        try:
            hour_str, minute_str = str(value).strip().split(":", 1)
            hour = int(hour_str)
            minute = int(minute_str)
        except (AttributeError, TypeError, ValueError):
            return 0, 0

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return 0, 0

        return hour, minute

    @classmethod
    def _get_current_slot(
        cls,
        now: datetime,
        start_time: str,
        interval_minutes: int,
    ) -> datetime:
        hour, minute = cls._parse_schedule_time(start_time)
        interval_minutes = max(1, min(interval_minutes, 1440))

        first_slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < first_slot:
            first_slot -= timedelta(days=1)

        elapsed_seconds = max(0, int((now - first_slot).total_seconds()))
        interval_seconds = interval_minutes * 60
        slot_offset = elapsed_seconds // interval_seconds
        return first_slot + timedelta(seconds=slot_offset * interval_seconds)

    @classmethod
    async def _load_config(cls, db_session) -> Dict[str, Any]:
        return {
            "enabled": await settings_service.get_bool_setting(
                db_session,
                "auto_reinvite_enabled",
                False,
            ),
            "start_time": await settings_service.get_setting(
                db_session,
                "auto_reinvite_start_time",
                cls.DEFAULT_START_TIME,
            ),
            "interval_minutes": max(
                1,
                min(
                    1440,
                    await settings_service.get_int_setting(
                        db_session,
                        "auto_reinvite_interval_minutes",
                        cls.DEFAULT_INTERVAL_MINUTES,
                    ),
                ),
            ),
            "batch_size": max(
                1,
                min(
                    500,
                    await settings_service.get_int_setting(
                        db_session,
                        "auto_reinvite_batch_size",
                        cls.DEFAULT_BATCH_SIZE,
                    ),
                ),
            ),
            "concurrency": max(
                1,
                min(
                    20,
                    await settings_service.get_int_setting(
                        db_session,
                        "auto_reinvite_concurrency",
                        cls.DEFAULT_CONCURRENCY,
                    ),
                ),
            ),
            "last_slot": await settings_service.get_setting(
                db_session,
                "auto_reinvite_last_slot",
                "",
            ),
        }

    @staticmethod
    async def _mark_last_slot(slot_value: str) -> None:
        async with AsyncSessionLocal() as db_session:
            await settings_service.update_setting(
                db_session,
                "auto_reinvite_last_slot",
                slot_value,
            )

    @staticmethod
    async def _store_last_result(snapshot: Dict[str, Any]) -> None:
        async with AsyncSessionLocal() as db_session:
            await settings_service.update_setting(
                db_session,
                "auto_reinvite_last_result",
                json.dumps(snapshot, ensure_ascii=False),
            )

    @staticmethod
    def _build_result_snapshot(
        summary: Dict[str, Any],
        *,
        trigger_source: str,
        slot_key: Optional[str],
    ) -> Dict[str, Any]:
        tz = pytz.timezone(settings.timezone)
        detail_items = list(summary.get("details") or [])[:12]
        return {
            "executed_at": datetime.now(tz).isoformat(),
            "trigger_source": trigger_source,
            "slot_key": slot_key,
            "success": bool(summary.get("success", False)),
            "processed": int(summary.get("processed", 0) or 0),
            "reinvited": int(summary.get("reinvited", 0) or 0),
            "skipped": int(summary.get("skipped", 0) or 0),
            "failed": int(summary.get("failed", 0) or 0),
            "total_candidates": int(summary.get("total_candidates", 0) or 0),
            "remaining_candidates": int(summary.get("remaining_candidates", 0) or 0),
            "batch_size": int(summary.get("batch_size", 0) or 0),
            "concurrency": int(summary.get("concurrency", 0) or 0),
            "message": summary.get("message") or "",
            "details": detail_items,
        }

    def _classify_candidate(
        self,
        record: RedemptionRecord,
        code: RedemptionCode,
        team: Team,
        parent_emails: set[str],
    ) -> Dict[str, Any]:
        child_email = self._normalize_email(getattr(record, "email", None))
        if not child_email:
            return {"eligible": False, "reason": "missing_child_email"}

        source_team_email = self._normalize_email(getattr(team, "email", None))
        if child_email in parent_emails or child_email == source_team_email:
            return {
                "eligible": False,
                "reason": "parent_or_source_email",
                "child_email": child_email,
                "source_team_email": source_team_email,
            }

        if not getattr(code, "has_warranty", False):
            return {"eligible": False, "reason": "non_warranty_code"}

        source_status = str(getattr(team, "status", "") or "").strip().lower()
        if source_status not in self.ELIGIBLE_SOURCE_STATUSES:
            return {
                "eligible": False,
                "reason": "source_team_not_reinviteable",
                "source_status": source_status or "unknown",
            }

        return {
            "eligible": True,
            "candidate": {
                "code": code.code,
                "email": record.email,
                "source_team_id": team.id,
                "source_team_email": team.email,
                "source_team_status": team.status,
            },
        }

    async def start(self) -> None:
        """启动后台巡检任务。"""
        if self._task and not self._task.done():
            return

        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("自动补邀后台任务已启动")

    async def stop(self) -> None:
        """停止后台巡检任务。"""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("自动补邀后台任务已停止")

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
                        config["interval_minutes"],
                    )
                    slot_key = current_slot.isoformat()
                    if slot_key != config["last_slot"]:
                        await self.process_once(slot_key, trigger_source="scheduled")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"自动补邀巡检异常: {exc}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                continue

    async def _execute_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        async with AsyncSessionLocal() as db_session:
            return await self._process_candidate(db_session, candidate)

    async def _run_candidates(
        self,
        candidates: List[Dict[str, Any]],
        concurrency: int,
    ) -> List[Dict[str, Any]]:
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def worker(candidate: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                return await self._execute_candidate(candidate)

        results = await asyncio.gather(
            *(worker(candidate) for candidate in candidates),
            return_exceptions=True,
        )

        normalized_results: List[Dict[str, Any]] = []
        for candidate, result in zip(candidates, results):
            if isinstance(result, Exception):
                normalized_results.append(
                    {
                        "status": "failed",
                        "code": candidate.get("code"),
                        "email": candidate.get("email"),
                        "reason": str(result) or "自动补邀执行异常",
                    }
                )
            else:
                normalized_results.append(result)

        return normalized_results

    async def process_once(
        self,
        slot_key: Optional[str] = None,
        *,
        ignore_enabled: bool = False,
        trigger_source: str = "event",
    ) -> Dict[str, Any]:
        """执行一轮自动补邀巡检。"""
        async with self._run_lock:
            async with AsyncSessionLocal() as db_session:
                config = await self._load_config(db_session)
                if not config["enabled"] and not ignore_enabled:
                    return {
                        "success": True,
                        "processed": 0,
                        "reinvited": 0,
                        "skipped": 0,
                        "failed": 0,
                        "total_candidates": 0,
                        "remaining_candidates": 0,
                        "details": [],
                        "message": "自动补邀未启用",
                    }

                candidates = await self._collect_candidates(db_session)

            total_candidates = len(candidates)
            candidates = candidates[: config["batch_size"]]
            remaining_candidates = max(0, total_candidates - len(candidates))

            summary = {
                "success": True,
                "processed": 0,
                "reinvited": 0,
                "skipped": 0,
                "failed": 0,
                "total_candidates": total_candidates,
                "remaining_candidates": remaining_candidates,
                "batch_size": config["batch_size"],
                "concurrency": config["concurrency"],
                "details": [],
                "message": "",
            }

            results = await self._run_candidates(candidates, config["concurrency"])

            for result in results:
                summary["processed"] += 1
                summary["details"].append(result)
                status = result.get("status")
                if status == "reinvited":
                    summary["reinvited"] += 1
                elif status == "failed":
                    summary["failed"] += 1
                else:
                    summary["skipped"] += 1

            summary["message"] = (
                f"自动补邀巡检完成: 处理 {summary['processed']} 条, "
                f"成功 {summary['reinvited']} 条, "
                f"跳过 {summary['skipped']} 条, "
                f"失败 {summary['failed']} 条"
            )
            if summary["remaining_candidates"] > 0:
                summary["message"] += f"，其余 {summary['remaining_candidates']} 条留待下轮处理"
            if summary["processed"] > 0:
                logger.info(summary["message"])
            elif slot_key:
                logger.info(
                    "自动补邀巡检完成: 当前时间槽无可处理账号 (并发=%s, 单轮上限=%s)",
                    config["concurrency"],
                    config["batch_size"],
                )

            if slot_key:
                await self._mark_last_slot(slot_key)
            await self._store_last_result(
                self._build_result_snapshot(
                    summary,
                    trigger_source=trigger_source,
                    slot_key=slot_key,
                )
            )
            return summary

    async def _collect_candidates(self, db_session) -> List[Dict[str, Any]]:
        parent_email_result = await db_session.execute(select(Team.email))
        parent_emails = {
            self._normalize_email(email)
            for email in parent_email_result.scalars().all()
            if email
        }

        # 只看每个子号邮箱最新的一条归属记录。
        # 如果用户已经在新的正常 Team 中，旧的封禁记录不应该再触发自动补邀。
        stmt = (
            select(RedemptionRecord, RedemptionCode, Team)
            .join(RedemptionCode, RedemptionRecord.code == RedemptionCode.code)
            .join(Team, RedemptionRecord.team_id == Team.id)
            .order_by(RedemptionRecord.redeemed_at.desc(), RedemptionRecord.id.desc())
        )

        rows = (await db_session.execute(stmt)).all()
        seen_emails = set()
        candidates: List[Dict[str, Any]] = []

        for record, code, team in rows:
            child_email = self._normalize_email(record.email)
            if not child_email or child_email in seen_emails:
                continue
            seen_emails.add(child_email)

            decision = self._classify_candidate(record, code, team, parent_emails)
            if not decision.get("eligible"):
                if decision.get("reason") == "parent_or_source_email":
                    logger.info(
                        "自动补邀跳过母号邮箱: code=%s email=%s source_team=%s",
                        code.code,
                        decision.get("child_email", child_email),
                        team.id,
                    )
                continue

            candidate = decision.get("candidate")
            if not candidate:
                logger.info(
                    "自动补邀跳过异常候选: code=%s email=%s source_team=%s",
                    code.code,
                    child_email,
                    team.id,
                )
                continue

            candidates.append(candidate)

        return candidates

    async def _process_candidate(self, db_session, candidate: Dict[str, Any]) -> Dict[str, Any]:
        code = candidate["code"]
        email = candidate["email"]

        warranty_check = await warranty_service.validate_warranty_reuse(
            db_session,
            code,
            email,
        )
        if not warranty_check.get("success"):
            return {
                "status": "failed",
                "code": code,
                "email": email,
                "reason": warranty_check.get("error") or "质保校验失败",
            }

        if not warranty_check.get("can_reuse"):
            return {
                "status": "skipped",
                "code": code,
                "email": email,
                "reason": warranty_check.get("reason") or "当前无需自动补邀",
            }

        redeem_result = await redeem_flow_service.redeem_and_join_team(
            email,
            code,
            None,
            db_session,
        )
        if redeem_result.get("success"):
            return {
                "status": "reinvited",
                "code": code,
                "email": email,
                "team_id": redeem_result.get("team_info", {}).get("id"),
            }

        return {
            "status": "failed",
            "code": code,
            "email": email,
            "reason": redeem_result.get("error") or "自动补邀失败",
        }


auto_reinvite_service = AutoReinviteService()
