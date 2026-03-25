import unittest

from app.webui import templates


class DummyRequest:
    def url_for(self, name, **path_params):
        if name == "static":
            path = path_params.get("path", "")
            return f"/static/{path}".replace("//", "/")
        return f"/{name}"


class SettingsTemplateTests(unittest.TestCase):
    def render_settings(self, *, active_page: str = "settings", settings_initial_panel: str = "") -> str:
        request = DummyRequest()
        return templates.get_template("admin/settings/index.html").render(
            {
                "request": request,
                "user": {"username": "admin"},
                "active_page": active_page,
                "settings_initial_panel": settings_initial_panel,
                "proxy_enabled": False,
                "proxy": "",
                "log_level": "INFO",
                "webhook_url": "",
                "low_stock_threshold": "10",
                "api_key": "",
                "after_sales_group_url": "https://t.me/example_support",
                "after_sales_group_text": "Support Group",
                "after_sales_group_subtitle": "Join the support group if needed",
                "default_team_seat_limit": "6",
                "auto_reinvite_enabled": "false",
                "auto_reinvite_start_time": "00:00",
                "auto_reinvite_interval_minutes": "5",
                "auto_reinvite_batch_size": "20",
                "auto_reinvite_concurrency": "1",
                "auto_reinvite_last_result": {
                    "executed_at_display": "2026-03-25 14:00:00",
                    "trigger_source_label": "手动执行",
                    "processed": 2,
                    "reinvited": 1,
                    "skipped": 1,
                    "failed": 0,
                    "remaining_candidates": 3,
                    "concurrency": 2,
                    "message": "自动补邀执行完成",
                    "details": [
                        {"email": "user@example.com", "code": "CODE-1", "status": "reinvited", "team_id": 88}
                    ],
                },
                "auto_status_refresh_enabled": "false",
                "auto_status_refresh_start_time": "03:00",
                "auto_status_refresh_interval_hours": "24",
            }
        )

    def test_renders_topbar_without_legacy_hero(self):
        html = self.render_settings()

        self.assertIn('class="settings-topbar"', html)
        self.assertNotIn("settings-hero-pill", html)
        self.assertNotIn("Automation Center", html)
        self.assertIn('data-panel="panel-after-sales"', html)
        self.assertIn('data-panel="panel-auto-reinvite"', html)
        self.assertIn('href="/admin/auto-reinvite"', html)
        self.assertIn("自动补邀规则", html)
        self.assertIn(">系统设置<", html)

    def test_renders_auto_reinvite_rule_list(self):
        html = self.render_settings()

        self.assertIn('id="autoReinviteForm"', html)
        self.assertIn('class="settings-list settings-rule-list"', html)
        self.assertIn('id="panel-auto-reinvite"', html)
        self.assertIn('id="autoReinviteStartTime"', html)
        self.assertIn('id="autoReinviteIntervalMinutes"', html)
        self.assertIn('id="autoReinviteBatchSize"', html)
        self.assertIn('id="autoReinviteConcurrency"', html)
        self.assertIn('id="runAutoReinviteNow"', html)
        self.assertIn('id="autoReinviteResultContent"', html)

    def test_sidebar_auto_reinvite_is_active_when_page_is_auto_reinvite(self):
        html = self.render_settings(active_page="auto_reinvite", settings_initial_panel="panel-auto-reinvite")

        self.assertIn('href="/admin/auto-reinvite"', html)
        self.assertIn('class="menu-item active"', html)
        self.assertIn(">自动补邀<", html)
        self.assertNotIn('class="settings-topbar"', html)
        self.assertNotIn('data-panel="panel-proxy"', html)
        self.assertIn("const serverDefaultPanel = 'panel-auto-reinvite';", html)


if __name__ == "__main__":
    unittest.main()
