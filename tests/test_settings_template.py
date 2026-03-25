import unittest

from app.webui import templates


class DummyRequest:
    def url_for(self, name, **path_params):
        if name == "static":
            path = path_params.get("path", "")
            return f"/static/{path}".replace("//", "/")
        return f"/{name}"


class SettingsTemplateTests(unittest.TestCase):
    def render_settings(self) -> str:
        request = DummyRequest()
        return templates.get_template("admin/settings/index.html").render(
            {
                "request": request,
                "user": {"username": "admin"},
                "active_page": "settings",
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
                "auto_reinvite_interval_seconds": "300",
                "auto_status_refresh_enabled": "false",
                "auto_status_refresh_start_time": "03:00",
                "auto_status_refresh_interval_hours": "24",
            }
        )

    def test_renders_topbar_without_legacy_hero(self):
        html = self.render_settings()

        self.assertIn('class="settings-topbar"', html)
        self.assertNotIn("settings-hero-pill", html)
        self.assertIn('data-panel="panel-after-sales"', html)

    def test_renders_auto_reinvite_rule_list(self):
        html = self.render_settings()

        self.assertIn('id="autoReinviteForm"', html)
        self.assertIn('class="settings-list settings-rule-list"', html)
        self.assertIn("panel-auto-reinvite", html)


if __name__ == "__main__":
    unittest.main()
