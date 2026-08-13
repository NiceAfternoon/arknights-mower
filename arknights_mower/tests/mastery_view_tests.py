import unittest
from unittest.mock import patch

from flask import Flask

from arknights_mower.views.mastery import mastery_bp


class TestMasteryRouteView(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(mastery_bp)
        self.client = app.test_client()

    @patch("arknights_mower.views.mastery.save_route")
    def test_route_post_forwards_all_persisted_settings(self, save_route_mock):
        response = self.client.post(
            "/mastery-route",
            json={
                "profession": "近卫",
                "supports": [],
                "optimal": True,
                "half_off": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        save_route_mock.assert_called_once_with(
            "近卫",
            "[]",
            is_default=0,
            optimal=True,
            half_off=False,
        )


if __name__ == "__main__":
    unittest.main()
