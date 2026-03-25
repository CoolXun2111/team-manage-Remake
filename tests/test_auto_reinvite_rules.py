import unittest
from types import SimpleNamespace

from app.services.auto_reinvite import AutoReinviteService


class AutoReinviteRuleTests(unittest.TestCase):
    def setUp(self):
        self.service = AutoReinviteService()

    def test_rejects_parent_or_source_email(self):
        record = SimpleNamespace(email="parent@example.com")
        code = SimpleNamespace(code="CODE-1", has_warranty=True)
        team = SimpleNamespace(id=1, email="source@example.com", status="banned")

        decision = self.service._classify_candidate(record, code, team, {"parent@example.com"})

        self.assertFalse(decision["eligible"])
        self.assertEqual(decision["reason"], "parent_or_source_email")

    def test_rejects_non_warranty_code(self):
        record = SimpleNamespace(email="child@example.com")
        code = SimpleNamespace(code="CODE-2", has_warranty=False)
        team = SimpleNamespace(id=2, email="source@example.com", status="banned")

        decision = self.service._classify_candidate(record, code, team, set())

        self.assertFalse(decision["eligible"])
        self.assertEqual(decision["reason"], "non_warranty_code")

    def test_rejects_non_banned_source_team(self):
        record = SimpleNamespace(email="child@example.com")
        code = SimpleNamespace(code="CODE-3", has_warranty=True)
        team = SimpleNamespace(id=3, email="source@example.com", status="error")

        decision = self.service._classify_candidate(record, code, team, set())

        self.assertFalse(decision["eligible"])
        self.assertEqual(decision["reason"], "source_team_not_reinviteable")

    def test_accepts_banned_warranty_child(self):
        record = SimpleNamespace(email="child@example.com")
        code = SimpleNamespace(code="CODE-4", has_warranty=True)
        team = SimpleNamespace(id=4, email="source@example.com", status="banned")

        decision = self.service._classify_candidate(record, code, team, {"parent@example.com"})

        self.assertTrue(decision["eligible"])
        self.assertEqual(decision["candidate"]["email"], "child@example.com")
        self.assertEqual(decision["candidate"]["source_team_status"], "banned")


if __name__ == "__main__":
    unittest.main()
