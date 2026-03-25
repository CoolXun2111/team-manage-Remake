import unittest

from app.webui import templates


class DummyRequest:
    def url_for(self, name, **path_params):
        if name == "static":
            path = path_params.get("path", "")
            return f"/static/{path}".replace("//", "/")
        return f"/{name}"


class AdminWorkspaceTemplateTests(unittest.TestCase):
    def test_codes_template_renders_workspace_hero(self):
        html = templates.get_template("admin/codes/index.html").render(
            {
                "request": DummyRequest(),
                "user": {"username": "admin"},
                "active_page": "codes",
                "stats": {"total": 10, "unused": 6, "used": 3, "expired": 1},
                "status_filter": "",
                "search": "",
                "codes": [],
                "pagination": {"total": 0, "per_page": 20, "total_pages": 0, "current_page": 1},
            }
        )

        self.assertIn("Code Workspace", html)
        self.assertIn("兑换码管理", html)
        self.assertIn("workspace-pills", html)
        self.assertIn("package-open", html)
        self.assertNotIn("🎫", html)

    def test_records_template_renders_workspace_hero(self):
        html = templates.get_template("admin/records/index.html").render(
            {
                "request": DummyRequest(),
                "user": {"username": "admin"},
                "active_page": "records",
                "stats": {"total": 10, "today": 1, "this_week": 4, "this_month": 8},
                "filters": {"email": "", "code": "", "team_id": "", "start_date": "", "end_date": ""},
                "records": [],
                "pagination": {"total": 0, "per_page": 20, "total_pages": 0, "current_page": 1},
            }
        )

        self.assertIn("Records Workspace", html)
        self.assertIn("使用记录", html)
        self.assertIn("workspace-pills", html)
        self.assertIn("clipboard-list", html)
        self.assertNotIn("📅", html)


if __name__ == "__main__":
    unittest.main()
