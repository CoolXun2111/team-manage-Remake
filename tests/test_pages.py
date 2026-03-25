import unittest

from fastapi.testclient import TestClient

from app.main import app


class PageSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def test_home_page_renders(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertNotIn("Internal Server Error", response.text)

    def test_login_page_renders(self):
        response = self.client.get("/login")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertIn('name="password"', response.text)

    def test_admin_page_redirects_to_login_when_not_authenticated(self):
        response = self.client.get(
            "/admin/",
            headers={"accept": "text/html"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers.get("location"), "/login")


if __name__ == "__main__":
    unittest.main()
