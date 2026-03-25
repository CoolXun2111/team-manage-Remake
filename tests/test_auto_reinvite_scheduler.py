import unittest
from datetime import datetime

import pytz

from app.services import auto_reinvite as auto_reinvite_module
from app.services.auto_reinvite import AutoReinviteService


class _DummySessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class AutoReinviteScheduleTests(unittest.TestCase):
    def test_get_current_slot_uses_start_time_and_interval_minutes(self):
        tz = pytz.timezone("Asia/Shanghai")
        now = tz.localize(datetime(2026, 3, 25, 10, 17, 0))

        slot = AutoReinviteService._get_current_slot(now, "00:00", 15)

        self.assertEqual(slot.hour, 10)
        self.assertEqual(slot.minute, 15)

    def test_get_current_slot_handles_previous_day_anchor(self):
        tz = pytz.timezone("Asia/Shanghai")
        now = tz.localize(datetime(2026, 3, 26, 0, 4, 0))

        slot = AutoReinviteService._get_current_slot(now, "23:30", 60)

        self.assertEqual(slot.year, 2026)
        self.assertEqual(slot.month, 3)
        self.assertEqual(slot.day, 25)
        self.assertEqual(slot.hour, 23)
        self.assertEqual(slot.minute, 30)


class AutoReinviteProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_once_respects_batch_size_and_marks_slot(self):
        service = AutoReinviteService()
        marked_slots = []
        stored_snapshots = []
        captured_candidates = []
        captured_concurrency = []

        async def fake_load_config(_db_session):
            return {
                "enabled": True,
                "start_time": "00:00",
                "interval_minutes": 5,
                "batch_size": 2,
                "concurrency": 3,
                "last_slot": "",
            }

        async def fake_collect_candidates(_db_session):
            return [
                {"code": "A", "email": "a@example.com"},
                {"code": "B", "email": "b@example.com"},
                {"code": "C", "email": "c@example.com"},
            ]

        async def fake_run_candidates(candidates, concurrency):
            captured_candidates.extend(candidates)
            captured_concurrency.append(concurrency)
            return [
                {"status": "reinvited", "code": "A", "email": "a@example.com"},
                {"status": "skipped", "code": "B", "email": "b@example.com", "reason": "already active"},
            ]

        async def fake_mark_last_slot(slot_value):
            marked_slots.append(slot_value)

        async def fake_store_last_result(snapshot):
            stored_snapshots.append(snapshot)

        original_session_local = auto_reinvite_module.AsyncSessionLocal
        original_load_config = service._load_config
        original_collect_candidates = service._collect_candidates
        original_run_candidates = service._run_candidates
        original_mark_last_slot = service._mark_last_slot
        original_store_last_result = service._store_last_result

        auto_reinvite_module.AsyncSessionLocal = lambda: _DummySessionContext()
        service._load_config = fake_load_config
        service._collect_candidates = fake_collect_candidates
        service._run_candidates = fake_run_candidates
        service._mark_last_slot = fake_mark_last_slot
        service._store_last_result = fake_store_last_result

        try:
            summary = await service.process_once("2026-03-25T00:00:00+08:00", trigger_source="scheduled")
        finally:
            auto_reinvite_module.AsyncSessionLocal = original_session_local
            service._load_config = original_load_config
            service._collect_candidates = original_collect_candidates
            service._run_candidates = original_run_candidates
            service._mark_last_slot = original_mark_last_slot
            service._store_last_result = original_store_last_result

        self.assertEqual(summary["processed"], 2)
        self.assertEqual(summary["reinvited"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["total_candidates"], 3)
        self.assertEqual(summary["remaining_candidates"], 1)
        self.assertEqual(summary["batch_size"], 2)
        self.assertEqual(summary["concurrency"], 3)
        self.assertEqual(captured_concurrency, [3])
        self.assertEqual(captured_candidates, [{"code": "A", "email": "a@example.com"}, {"code": "B", "email": "b@example.com"}])
        self.assertEqual(marked_slots, ["2026-03-25T00:00:00+08:00"])
        self.assertEqual(stored_snapshots[0]["trigger_source"], "scheduled")
        self.assertEqual(stored_snapshots[0]["remaining_candidates"], 1)

    async def test_process_once_can_run_manually_when_disabled(self):
        service = AutoReinviteService()
        stored_snapshots = []

        async def fake_load_config(_db_session):
            return {
                "enabled": False,
                "start_time": "00:00",
                "interval_minutes": 5,
                "batch_size": 5,
                "concurrency": 1,
                "last_slot": "",
            }

        async def fake_collect_candidates(_db_session):
            return [{"code": "A", "email": "manual@example.com"}]

        async def fake_run_candidates(candidates, concurrency):
            return [{"status": "reinvited", "code": candidates[0]["code"], "email": candidates[0]["email"], "team_id": 9}]

        async def fake_store_last_result(snapshot):
            stored_snapshots.append(snapshot)

        original_session_local = auto_reinvite_module.AsyncSessionLocal
        original_load_config = service._load_config
        original_collect_candidates = service._collect_candidates
        original_run_candidates = service._run_candidates
        original_store_last_result = service._store_last_result

        auto_reinvite_module.AsyncSessionLocal = lambda: _DummySessionContext()
        service._load_config = fake_load_config
        service._collect_candidates = fake_collect_candidates
        service._run_candidates = fake_run_candidates
        service._store_last_result = fake_store_last_result

        try:
            summary = await service.process_once(ignore_enabled=True, trigger_source="manual")
        finally:
            auto_reinvite_module.AsyncSessionLocal = original_session_local
            service._load_config = original_load_config
            service._collect_candidates = original_collect_candidates
            service._run_candidates = original_run_candidates
            service._store_last_result = original_store_last_result

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["reinvited"], 1)
        self.assertEqual(stored_snapshots[0]["trigger_source"], "manual")


if __name__ == "__main__":
    unittest.main()
