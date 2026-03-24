"""
Cobertura: OpenRouter credits (fetch HTTP), persistência/refresh, GET /usage/openrouter/credits.

    uv run python -m unittest discover -s test -v
    ./test/run_tests.sh   # coverage + HTML em test/result/
"""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.routes.usage import UsageCaller, get_usage_caller
from src.gateway.openrouter_credits import _credits_url, fetch_openrouter_credits
from src.usage.openrouter_credits_state import refresh_openrouter_credits_for_api


def _settings_credits(
    *,
    upstream_url: str = "https://openrouter.ai/api/v1",
    openrouter_api_key: str = "sk-or-test",
    openrouter_management_api_key: str | None = None,
    openrouter_credits_alert_threshold_usd: float = 10.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        upstream_url=upstream_url,
        openrouter_api_key=openrouter_api_key,
        openrouter_management_api_key=openrouter_management_api_key,
        openrouter_credits_alert_threshold_usd=openrouter_credits_alert_threshold_usd,
    )


def _httpx_client_mock(response: MagicMock) -> MagicMock:
    """AsyncClient() como context manager; .get async devolve response."""
    inner = MagicMock()
    inner.get = AsyncMock(return_value=response)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=inner)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestCreditsUrl(unittest.TestCase):
    def test_credits_url_trims_slash(self) -> None:
        s = _settings_credits(upstream_url="https://x.com/api/v1/")
        self.assertEqual(_credits_url(s), "https://x.com/api/v1/credits")


class TestFetchOpenrouterCredits(unittest.IsolatedAsyncioTestCase):
    async def test_empty_key_returns_none(self) -> None:
        s = _settings_credits(openrouter_api_key="")
        self.assertIsNone(await fetch_openrouter_credits(s))

    async def test_management_key_preferred_when_set(self) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.text = ""
        resp.json.return_value = {"data": {"total_credits": 10, "total_usage": 3}}

        with patch(
            "src.gateway.openrouter_credits.httpx.AsyncClient",
            return_value=_httpx_client_mock(resp),
        ) as ac:
            s = _settings_credits(
                openrouter_api_key="sk-chat",
                openrouter_management_api_key="sk-mgmt",
            )
            out = await fetch_openrouter_credits(s)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["remaining"], 7.0)
        inner = await ac.return_value.__aenter__()
        inner.get.assert_awaited_once()
        call_kw = inner.get.await_args[1]
        self.assertIn("sk-mgmt", call_kw["headers"]["Authorization"])

    async def test_200_parses_data(self) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.text = ""
        resp.json.return_value = {"data": {"total_credits": 100, "total_usage": 60.5}}
        with patch(
            "src.gateway.openrouter_credits.httpx.AsyncClient",
            return_value=_httpx_client_mock(resp),
        ):
            out = await fetch_openrouter_credits(_settings_credits())
        assert out is not None
        self.assertAlmostEqual(out["remaining"], 39.5)
        self.assertEqual(out["total_credits"], 100.0)
        self.assertEqual(out["total_usage"], 60.5)

    async def test_remaining_never_negative(self) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.text = ""
        resp.json.return_value = {"data": {"total_credits": 10, "total_usage": 50}}
        with patch(
            "src.gateway.openrouter_credits.httpx.AsyncClient",
            return_value=_httpx_client_mock(resp),
        ):
            out = await fetch_openrouter_credits(_settings_credits())
        assert out is not None
        self.assertEqual(out["remaining"], 0.0)

    async def test_403_returns_none(self) -> None:
        resp = MagicMock(status_code=403, text="no")
        with patch(
            "src.gateway.openrouter_credits.httpx.AsyncClient",
            return_value=_httpx_client_mock(resp),
        ):
            self.assertIsNone(await fetch_openrouter_credits(_settings_credits()))

    async def test_non_200_returns_none(self) -> None:
        resp = MagicMock(status_code=500, text="err")
        with patch(
            "src.gateway.openrouter_credits.httpx.AsyncClient",
            return_value=_httpx_client_mock(resp),
        ):
            self.assertIsNone(await fetch_openrouter_credits(_settings_credits()))

    async def test_request_error_returns_none(self) -> None:
        req = httpx.Request("GET", "https://openrouter.ai/api/v1/credits")
        inner = MagicMock()
        inner.get = AsyncMock(side_effect=httpx.ConnectError("offline", request=req))
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=inner)
        cm.__aexit__ = AsyncMock(return_value=False)
        with patch("src.gateway.openrouter_credits.httpx.AsyncClient", return_value=cm):
            self.assertIsNone(await fetch_openrouter_credits(_settings_credits()))

    async def test_invalid_json_returns_none(self) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = json.JSONDecodeError("x", "", 0)
        with patch(
            "src.gateway.openrouter_credits.httpx.AsyncClient",
            return_value=_httpx_client_mock(resp),
        ):
            self.assertIsNone(await fetch_openrouter_credits(_settings_credits()))

    async def test_non_numeric_credits_returns_none(self) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.text = ""
        resp.json.return_value = {"data": {"total_credits": "not-a-number", "total_usage": 0}}
        with patch(
            "src.gateway.openrouter_credits.httpx.AsyncClient",
            return_value=_httpx_client_mock(resp),
        ):
            self.assertIsNone(await fetch_openrouter_credits(_settings_credits()))


class TestRefreshOpenrouterCredits(unittest.IsolatedAsyncioTestCase):
    async def test_success_persists_show_alert_false_above_threshold(self) -> None:
        snap = {"remaining": 50.0, "total_credits": 100.0, "total_usage": 50.0}
        with (
            patch(
                "src.usage.openrouter_credits_state.fetch_openrouter_credits",
                new_callable=AsyncMock,
                return_value=snap,
            ),
            patch(
                "src.usage.openrouter_credits_state._upsert",
                new_callable=AsyncMock,
            ) as up,
        ):
            out = await refresh_openrouter_credits_for_api(
                _settings_credits(openrouter_credits_alert_threshold_usd=10.0)
            )
        up.assert_awaited_once()
        self.assertFalse(out["show_alert"])
        self.assertFalse(out["openrouter_unavailable"])
        self.assertEqual(out["remaining_usd"], 50.0)

    async def test_show_alert_true_at_threshold(self) -> None:
        snap = {"remaining": 10.0, "total_credits": 20.0, "total_usage": 10.0}
        with (
            patch(
                "src.usage.openrouter_credits_state.fetch_openrouter_credits",
                new_callable=AsyncMock,
                return_value=snap,
            ),
            patch("src.usage.openrouter_credits_state._upsert", new_callable=AsyncMock),
        ):
            out = await refresh_openrouter_credits_for_api(
                _settings_credits(openrouter_credits_alert_threshold_usd=10.0)
            )
        self.assertTrue(out["show_alert"])

    async def test_fetch_fails_no_stale(self) -> None:
        with (
            patch(
                "src.usage.openrouter_credits_state.fetch_openrouter_credits",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.usage.openrouter_credits_state._read_row",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            out = await refresh_openrouter_credits_for_api(_settings_credits())
        self.assertTrue(out["openrouter_unavailable"])
        self.assertIsNone(out["remaining_usd"])
        self.assertFalse(out["show_alert"])

    async def test_fetch_fails_returns_stale(self) -> None:
        from datetime import datetime

        stale = {
            "remaining_usd": 3.0,
            "total_credits_usd": 10.0,
            "total_usage_usd": 7.0,
            "show_alert": True,
            "checked_at": datetime(2025, 6, 1, 12, 0, 0),
            "fetch_ok": True,
        }
        with (
            patch(
                "src.usage.openrouter_credits_state.fetch_openrouter_credits",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.usage.openrouter_credits_state._read_row",
                new_callable=AsyncMock,
                return_value=stale,
            ),
        ):
            out = await refresh_openrouter_credits_for_api(_settings_credits())
        self.assertTrue(out["openrouter_unavailable"])
        self.assertTrue(out.get("stale"))
        self.assertEqual(out["remaining_usd"], 3.0)
        self.assertTrue(out["show_alert"])
        self.assertIn("T12:00:00", out["checked_at"] or "")

    async def test_fetch_fails_stale_string_checked_at(self) -> None:
        stale = {
            "remaining_usd": 1.0,
            "total_credits_usd": None,
            "total_usage_usd": None,
            "show_alert": False,
            "checked_at": "fixed-timestamp",
            "fetch_ok": False,
        }
        with (
            patch(
                "src.usage.openrouter_credits_state.fetch_openrouter_credits",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.usage.openrouter_credits_state._read_row",
                new_callable=AsyncMock,
                return_value=stale,
            ),
        ):
            out = await refresh_openrouter_credits_for_api(_settings_credits())
        self.assertEqual(out["checked_at"], "fixed-timestamp")

    async def test_upsert_runtime_error_still_returns_payload(self) -> None:
        snap = {"remaining": 1.0, "total_credits": 5.0, "total_usage": 4.0}
        with (
            patch(
                "src.usage.openrouter_credits_state.fetch_openrouter_credits",
                new_callable=AsyncMock,
                return_value=snap,
            ),
            patch(
                "src.usage.openrouter_credits_state._upsert",
                new_callable=AsyncMock,
                side_effect=RuntimeError("no table"),
            ),
        ):
            out = await refresh_openrouter_credits_for_api(_settings_credits())
        self.assertFalse(out["openrouter_unavailable"])
        self.assertFalse(out["persisted"])
        self.assertIn("persist_error", out)

    async def test_upsert_generic_exception_returns_payload(self) -> None:
        snap = {"remaining": 2.0, "total_credits": 5.0, "total_usage": 3.0}
        with (
            patch(
                "src.usage.openrouter_credits_state.fetch_openrouter_credits",
                new_callable=AsyncMock,
                return_value=snap,
            ),
            patch(
                "src.usage.openrouter_credits_state._upsert",
                new_callable=AsyncMock,
                side_effect=ValueError("db down"),
            ),
            patch("src.usage.openrouter_credits_state.logger"),
        ):
            out = await refresh_openrouter_credits_for_api(_settings_credits())
        self.assertFalse(out["openrouter_unavailable"])
        self.assertEqual(out["persist_error"], "db down")


class TestUsageOpenrouterCreditsEndpoint(unittest.TestCase):
    """Evita Postgres real no lifespan (CI / sem Docker)."""

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    @staticmethod
    def _patch_key_store_startup() -> MagicMock:
        mock_ks = MagicMock()
        mock_ks.startup = AsyncMock()
        mock_ks.shutdown = AsyncMock()
        mock_ks.cache_size = 0
        return mock_ks

    def test_app_key_forbidden_403(self) -> None:
        def fake_caller() -> UsageCaller:
            return UsageCaller(is_admin=False, app_id="x")

        app.dependency_overrides[get_usage_caller] = fake_caller
        mock_ks = self._patch_key_store_startup()
        with patch("src.gateway.key_store.init_key_store", return_value=mock_ks):
            with TestClient(app) as client:
                r = client.get("/usage/openrouter/credits")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"]["error"], "forbidden")

    def test_admin_returns_refresh_payload(self) -> None:
        def fake_caller() -> UsageCaller:
            return UsageCaller(is_admin=True, app_id=None)

        app.dependency_overrides[get_usage_caller] = fake_caller
        payload = {
            "remaining_usd": 12.5,
            "total_credits_usd": 100.0,
            "total_usage_usd": 87.5,
            "show_alert": False,
            "alert_threshold_usd": 10.0,
            "checked_at": "2026-01-01T00:00:00+00:00",
            "openrouter_unavailable": False,
        }

        mock_ks = self._patch_key_store_startup()
        with patch("src.gateway.key_store.init_key_store", return_value=mock_ks):
            with patch(
                "src.api.routes.usage.refresh_openrouter_credits_for_api",
                new_callable=AsyncMock,
                return_value=payload,
            ):
                with TestClient(app) as client:
                    r = client.get("/usage/openrouter/credits")

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), payload)


if __name__ == "__main__":
    unittest.main()
