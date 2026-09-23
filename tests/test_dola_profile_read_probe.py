"""Offline classification tests for the non-generating Dola profile probe."""
from __future__ import annotations

import unittest

from tools.dola_profile_read_probe import _qualified


class DolaProfileReadProbeTests(unittest.TestCase):
    def setUp(self):
        self.control = {
            "http_status": 200,
            "final_host": "www.dola.com",
            "login_button_visible": True,
            "session_cookie_names": [],
        }
        self.profile = {
            "http_status": 200,
            "final_host": "www.dola.com",
            "login_button_visible": False,
            "session_cookie_names": ["sessionid_ss"],
        }

    def test_requires_distinguishing_negative_control(self):
        self.assertTrue(_qualified(self.control, self.profile))
        self.control["login_button_visible"] = False
        self.assertFalse(_qualified(self.control, self.profile))

    def test_requires_session_and_no_login_button(self):
        self.profile["session_cookie_names"] = []
        self.assertFalse(_qualified(self.control, self.profile))
        self.profile["session_cookie_names"] = ["sessionid"]
        self.profile["login_button_visible"] = True
        self.assertFalse(_qualified(self.control, self.profile))

    def test_http_or_host_mismatch_fails_closed(self):
        self.profile["http_status"] = 302
        self.assertFalse(_qualified(self.control, self.profile))
        self.profile["http_status"] = 200
        self.profile["final_host"] = "dola.com.evil.invalid"
        self.assertFalse(_qualified(self.control, self.profile))


if __name__ == "__main__":
    unittest.main()
