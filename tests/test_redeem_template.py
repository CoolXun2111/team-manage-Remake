import unittest

from app.webui import templates


class DummyRequest:
    def url_for(self, name, **path_params):
        if name == "static":
            path = path_params.get("path", "")
            return f"/static/{path}".replace("//", "/")
        return f"/{name}"


class RedeemTemplateTests(unittest.TestCase):
    def render(
        self,
        after_sales_group_url="",
        after_sales_group_text="售后群入口",
        after_sales_group_subtitle="兑换后遇到问题，可直接进群联系售后处理",
    ):
        request = DummyRequest()
        return templates.get_template("user/redeem.html").render(
            {
                "request": request,
                "remaining_spots": 8,
                "after_sales_group_url": after_sales_group_url,
                "after_sales_group_text": after_sales_group_text,
                "after_sales_group_subtitle": after_sales_group_subtitle,
            }
        )

    def test_renders_support_entry_when_link_is_configured(self):
        html = self.render(
            "https://t.me/example_support",
            "联系客服群",
            "有问题可进群联系售后",
        )

        self.assertIn("联系客服群", html)
        self.assertIn("有问题可进群联系售后", html)
        self.assertIn("https://t.me/example_support", html)

    def test_hides_support_entry_when_link_is_missing(self):
        html = self.render("")

        self.assertNotIn("售后群入口", html)

    def test_uses_default_support_text_when_text_is_blank(self):
        html = self.render("https://t.me/example_support", "")

        self.assertIn("售后群入口", html)

    def test_uses_default_support_subtitle_when_subtitle_is_blank(self):
        html = self.render("https://t.me/example_support", "联系客服群", "")

        self.assertIn("兑换后遇到问题，可直接进群联系售后处理", html)


if __name__ == "__main__":
    unittest.main()
