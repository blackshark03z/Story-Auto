"""Offline tests for Story Auto's supported Python installation contract."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


class DependencyContractTests(unittest.TestCase):
    def test_flow_locator_transport_is_a_declared_production_dependency(self):
        root = Path(__file__).resolve().parents[1]
        requirements = (root / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("playwright>=1.40,<2", requirements)
        self.assertIsNotNone(importlib.util.find_spec("playwright"))
        from playwright.sync_api import sync_playwright
        self.assertTrue(callable(sync_playwright))
