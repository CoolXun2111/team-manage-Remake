import unittest
from types import SimpleNamespace

from app.services.team import TeamService


class DeviceAuthErrorTests(unittest.TestCase):
    def setUp(self):
        self.service = TeamService()
        self.team = SimpleNamespace(subscription_plan="team", plan_type="team")

    def test_workspace_plan_required_error_is_translated(self):
        result = self.service._normalize_device_auth_error(
            "Workspace plan required.",
            team=self.team,
        )

        self.assertEqual(result["error_code"], "workspace_plan_required")
        self.assertIn("team", result["error"])
        self.assertIn("Workspace plan", result["error"])
        self.assertNotEqual(result["error"], "Workspace plan required.")

    def test_unknown_feature_error_is_translated(self):
        result = self.service._normalize_device_auth_error(
            "unknown beta feature",
            team=self.team,
        )

        self.assertEqual(result["error_code"], "device_auth_feature_unavailable")
        self.assertNotIn("unknown beta feature", result["error"])


if __name__ == "__main__":
    unittest.main()
