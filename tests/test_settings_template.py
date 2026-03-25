import unittest

from app.webui import templates


class DummyRequest:
    def url_for(self, name, **path_params):
        if name == "static":
            path = path_params.get("path", "")
            return f"/static/{path}".replace("//", "/")
        return f"/{name}"


class SettingsTemplateTests(unittest.TestCase):
    def test_renders_after_sales_panel(self):
        request = DummyRequest()
        html = templates.get_template("admin/settings/index.html").render(
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
                "after_sales_group_text": "联系客服群",
                "after_sales_group_subtitle": "有问题可进群联系售后",
                "default_team_seat_limit": "6",
                "auto_reinvite_enabled": "false",
                "auto_reinvite_interval_seconds": "300",
                "auto_status_refresh_enabled": "false",
                "auto_status_refresh_start_time": "03:00",
                "auto_status_refresh_interval_hours": "24",
            }
        )

        self.assertIn("panel-after-sales", html)
        self.assertIn('id="afterSalesForm"', html)
        self.assertIn("联系客服群", html)


if __name__ == "__main__":
    unittest.main()
