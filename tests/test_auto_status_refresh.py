import unittest
from datetime import datetime

import pytz

from app.services.auto_status_refresh import AutoStatusRefreshService
from app.services.team import team_service


class AutoStatusRefreshScheduleTests(unittest.TestCase):
    def test_get_current_slot_uses_start_time_and_interval(self):
        tz = pytz.timezone("Asia/Shanghai")
        now = tz.localize(datetime(2026, 3, 25, 10, 20, 0))

        slot = AutoStatusRefreshService._get_current_slot(now, "03:00", 6)

        self.assertEqual(slot.hour, 9)
        self.assertEqual(slot.minute, 0)

    def test_get_current_slot_handles_previous_day_anchor(self):
        tz = pytz.timezone("Asia/Shanghai")
        now = tz.localize(datetime(2026, 3, 26, 1, 30, 0))

        slot = AutoStatusRefreshService._get_current_slot(now, "23:00", 6)

        self.assertEqual(slot.year, 2026)
        self.assertEqual(slot.month, 3)
        self.assertEqual(slot.day, 25)
        self.assertEqual(slot.hour, 23)
        self.assertEqual(slot.minute, 0)


class AutoStatusRefreshProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_team_ids_prioritizes_problematic_and_stale_teams(self):
        class _DummyResult:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        class _DummySession:
            async def execute(self, _stmt):
                return _DummyResult(
                    [
                        (1, "active", datetime(2026, 3, 25, 10, 0, 0)),
                        (2, "error", datetime(2026, 3, 25, 11, 0, 0)),
                        (3, "full", None),
                        (4, "expired", datetime(2026, 3, 24, 8, 0, 0)),
                        (5, "active", None),
                        (6, "unknown", None),
                    ]
                )

        team_ids = await AutoStatusRefreshService._get_team_ids(_DummySession())
        self.assertEqual(team_ids, [2, 4, 3, 5, 1, 6])

    async def test_process_once_summarizes_results_and_marks_slot(self):
        service = AutoStatusRefreshService()
        marked_slots = []

        async def fake_get_team_ids(_db_session):
            return [101, 102, 103]

        async def fake_mark_last_slot(slot_value):
            marked_slots.append(slot_value)

        async def fake_sync_team_info(team_id, _db_session, force_refresh=False):
            self.assertFalse(force_refresh)
            if team_id == 102:
                return {"success": False, "error": "sync failed", "message": None}
            return {"success": True, "error": None, "message": "ok"}

        original_get_team_ids = service._get_team_ids
        original_mark_last_slot = service._mark_last_slot
        original_sync_team_info = team_service.sync_team_info

        service._get_team_ids = fake_get_team_ids
        service._mark_last_slot = fake_mark_last_slot
        team_service.sync_team_info = fake_sync_team_info

        try:
            summary = await service.process_once("2026-03-25T03:00:00+08:00")
        finally:
            service._get_team_ids = original_get_team_ids
            service._mark_last_slot = original_mark_last_slot
            team_service.sync_team_info = original_sync_team_info

        self.assertEqual(summary["processed"], 3)
        self.assertEqual(summary["succeeded"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["concurrency"], service.DEFAULT_CONCURRENCY)
        self.assertEqual(marked_slots, ["2026-03-25T03:00:00+08:00"])


if __name__ == "__main__":
    unittest.main()
