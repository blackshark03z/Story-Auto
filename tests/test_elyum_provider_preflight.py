from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from story_auto.application.operator import OperatorService
from story_auto.providers.elyum_seedance.client import ElyumSeedanceClient, ElyumSeedanceError


class _CatalogSession:
    def __init__(self):
        self.calls = []

    def call_tool(self, name, arguments=None):
        arguments = dict(arguments or {})
        self.calls.append((name, arguments))
        if name == "elyum_models":
            return {
                "roles": {
                    "video": [
                        {"id": "seedance-2-5", "name": "Seedance 2.5"},
                        {"slug": "seedance-2-fast", "name": "Seedance 2.0 Fast"},
                        {"id": "kling-3", "name": "Kling 3"},
                    ]
                }
            }
        raise AssertionError(name)


class _PreflightClient:
    def __init__(self, *args, **kwargs):
        self.estimate_calls = []

    def readiness(self):
        return {"status": "READY", "provider_id": "elyum_seedance"}

    def account_balance(self):
        return 150

    def seedance_model_ids(self):
        return ["seedance-2-5", "seedance-broken", "seedance-2-fast"]

    def estimate_video(self, *, model, duration, mode, resolution=None):
        self.estimate_calls.append((model, duration, mode, resolution))
        if model == "seedance-broken":
            raise ElyumSeedanceError("CAPABILITY_OR_REQUEST_INVALID")
        return 54 if model == "seedance-2-5" else 30


class _NoModelClient(_PreflightClient):
    def seedance_model_ids(self):
        return []


class ElyumProviderPreflightTests(unittest.TestCase):
    def test_live_catalog_parser_returns_seedance_ids_only(self):
        session = _CatalogSession()
        client = ElyumSeedanceClient(key="fixture", session=session)
        self.assertEqual(client.seedance_model_ids(), ["seedance-2-5", "seedance-2-fast"])
        self.assertEqual([name for name, _ in session.calls], ["elyum_models"])

    def test_settings_preflight_verifies_t2v_by_read_only_estimate(self):
        with tempfile.TemporaryDirectory() as root, \
             patch("story_auto.application.operator.ElyumSeedanceClient", _PreflightClient), \
             patch("story_auto.application.operator.provider_key_status", return_value={
                 "configured": True, "count": 1, "source": "DPAPI_STORE", "removable": True,
             }):
            result = OperatorService(root).test_elyum_connection()
        self.assertEqual(result["status"], "CONNECTED")
        self.assertTrue(result["live_verified"])
        self.assertEqual(result["balance"], 150)
        self.assertEqual(result["seedance_t2v_models"], [
            {"model_id": "seedance-2-5", "estimated_credits_6s": 54},
            {"model_id": "seedance-2-fast", "estimated_credits_6s": 30},
        ])

    def test_settings_preflight_fails_closed_without_verified_seedance_t2v(self):
        with tempfile.TemporaryDirectory() as root, \
             patch("story_auto.application.operator.ElyumSeedanceClient", _NoModelClient), \
             patch("story_auto.application.operator.provider_key_status", return_value={
                 "configured": True, "count": 1, "source": "DPAPI_STORE", "removable": True,
             }):
            result = OperatorService(root).test_elyum_connection()
        self.assertEqual(result["status"], "ERROR")
        self.assertFalse(result["live_verified"])
        self.assertEqual(result["reason_code"], "ELYUM_SEEDANCE_T2V_MODEL_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
