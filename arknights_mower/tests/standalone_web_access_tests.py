"""Independent desktop access settings retain the current session credential."""

import os
import unittest
from unittest.mock import patch

import yaml

from arknights_mower.tests import device_settings_route_tests as settings_routes
from arknights_mower.utils import config
from arknights_mower.utils.configuration_secrets import conf_secrets_path
from arknights_mower.utils.credential_store import read_credentials
from webview_ui import desktop_port


class StandaloneWebAccessTests(unittest.TestCase):
    def setUp(self):
        settings_routes.DeviceSettingsRouteTests.setUp(self)
        self.enterContext(
            patch("arknights_mower.utils.managed_device.enabled", return_value=False)
        )

    def test_saved_access_values_apply_to_next_launch_without_rotating_session(self):
        response = self.client.patch(
            "/conf",
            headers=self.headers,
            json={"webview": {"port": 58123, "token": "synthetic-next-token"}},
        )
        self.assertEqual(response.status_code, 200, response.json)
        saved = yaml.safe_load(self.path.read_text(encoding="utf-8"))["webview"]
        self.assertEqual(saved["port"], 58123)
        self.assertNotIn("token", saved)
        self.assertEqual(
            read_credentials(conf_secrets_path(self.path))["MOWER_WEBVIEW_TOKEN"],
            "synthetic-next-token",
        )
        self.assertNotIn(
            b"synthetic-next-token", conf_secrets_path(self.path).read_bytes()
        )
        self.assertEqual(desktop_port(config.conf.webview, False), 58123)
        self.assertEqual(self.server.app.token, "device-token")
        self.assertEqual(
            self.client.get("/conf", headers=self.headers).status_code, 200
        )
        self.assertEqual(
            self.client.get(
                "/conf", headers={"token": "synthetic-next-token"}
            ).status_code,
            403,
        )

    def test_access_save_requires_current_session_token_before_parsing(self):
        from flask import Request

        before = self.path.read_bytes()
        with patch.object(Request, "get_json", side_effect=AssertionError("parsed")):
            for token in (None, "invalid-token"):
                headers = {} if token is None else {"token": token}
                response = self.client.patch(
                    "/conf", headers=headers, json={"webview": {"port": 58123}}
                )
                self.assertEqual(response.status_code, 403)
        self.assertEqual(self.path.read_bytes(), before)

    def test_remote_container_cannot_clear_its_access_token(self):
        before = self.path.read_bytes()
        previous = config.conf.webview.token
        with patch.dict(os.environ, {"MOWER_REQUIRE_WEB_TOKEN": "1"}):
            for method in (self.client.post, self.client.patch):
                response = method(
                    "/conf", headers=self.headers, json={"webview": {"token": ""}}
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json["message"], "此部署允许远程访问，访问令牌不能为空。"
                )
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(config.conf.webview.token, previous)
        self.assertEqual(self.server.app.token, "device-token")
