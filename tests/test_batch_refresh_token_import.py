import unittest

from app.services.team import TeamService
from app.utils.token_parser import TokenParser


class TokenParserTests(unittest.TestCase):
    def test_parse_team_import_text_supports_refresh_token_only_lines(self):
        parser = TokenParser()

        results = parser.parse_team_import_text("rt-first-token\nrt-second-token\n")

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["refresh_token"], "rt-first-token")
        self.assertIsNone(results[0]["token"])
        self.assertEqual(results[1]["refresh_token"], "rt-second-token")


class BatchRefreshTokenImportTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_import_uses_shared_client_id_and_deduplicates_rt_only_lines(self):
        service = TeamService()
        import_calls = []

        service.token_parser.parse_team_import_text = lambda _text: [
            {"token": None, "email": None, "account_id": None, "refresh_token": "rt-first", "session_token": None, "client_id": None},
            {"token": None, "email": None, "account_id": None, "refresh_token": "rt-first", "session_token": None, "client_id": None},
            {"token": None, "email": None, "account_id": None, "refresh_token": "rt-second", "session_token": None, "client_id": "app_inline"},
        ]

        async def fake_import_team_single(**kwargs):
            import_calls.append(kwargs)
            return {
                "success": True,
                "team_id": len(import_calls),
                "email": kwargs.get("email") or f"user{len(import_calls)}@example.com",
                "message": "ok",
                "error": None,
            }

        service.import_team_single = fake_import_team_single

        events = []
        async for event in service.import_team_batch(
            text="ignored",
            db_session=object(),
            shared_client_id="app_shared",
        ):
            events.append(event)

        self.assertEqual(len(import_calls), 2)
        self.assertEqual(import_calls[0]["refresh_token"], "rt-first")
        self.assertEqual(import_calls[0]["client_id"], "app_shared")
        self.assertEqual(import_calls[1]["refresh_token"], "rt-second")
        self.assertEqual(import_calls[1]["client_id"], "app_inline")

        self.assertEqual(events[0]["type"], "start")
        self.assertEqual(events[0]["total"], 2)
        self.assertEqual(events[-1]["type"], "finish")
        self.assertEqual(events[-1]["success_count"], 2)
        self.assertEqual(events[-1]["failed_count"], 0)


if __name__ == "__main__":
    unittest.main()
