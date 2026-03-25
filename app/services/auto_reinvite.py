import asyncio
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import RedemptionCode, RedemptionRecord, Team
from app.services.redeem_flow import redeem_flow_service
from app.services.settings import settings_service
from app.services.warranty import warranty_service

logger = logging.getLogger(__name__)


class AutoReinviteService:
    """失效母号自动补邀服务。"""
    ELIGIBLE_SOURCE_STATUSES = {"banned"}

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._run_lock = asyncio.Lock()

    @staticmethod
    def _normalize_email(email: Optional[str]) -> str:
        return (email or "").strip().lower()

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
            interval_seconds = 300
            try:
                async with AsyncSessionLocal() as db_session:
                    interval_seconds = max(
                        60,
                        await settings_service.get_int_setting(
                            db_session,
                            "auto_reinvite_interval_seconds",
                            300,
                        ),
                    )
                    enabled = await settings_service.get_bool_setting(
                        db_session,
                        "auto_reinvite_enabled",
                        False,
                    )

                if enabled:
                    await self.process_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"自动补邀巡检异常: {exc}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def process_once(self) -> Dict[str, Any]:
        """执行一轮自动补邀巡检。"""
        async with self._run_lock:
            async with AsyncSessionLocal() as db_session:
                enabled = await settings_service.get_bool_setting(
                    db_session,
                    "auto_reinvite_enabled",
                    False,
                )
                if not enabled:
                    return {
                        "success": True,
                        "processed": 0,
                        "reinvited": 0,
                        "skipped": 0,
                        "failed": 0,
                        "details": [],
                        "message": "自动补邀未启用",
                    }

                candidates = await self._collect_candidates(db_session)

            summary = {
                "success": True,
                "processed": 0,
                "reinvited": 0,
                "skipped": 0,
                "failed": 0,
                "details": [],
                "message": "",
            }

            for candidate in candidates:
                summary["processed"] += 1
                async with AsyncSessionLocal() as db_session:
                    result = await self._process_candidate(db_session, candidate)

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
            if summary["processed"] > 0:
                logger.info(summary["message"])
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
