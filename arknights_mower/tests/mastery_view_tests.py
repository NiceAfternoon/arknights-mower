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


class TestMasteryPlanView(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(mastery_bp)
        self.client = app.test_client()

    @patch("arknights_mower.views.mastery.get_skill_data")
    @patch("arknights_mower.views.mastery.get_all_history")
    @patch("arknights_mower.views.mastery.get_failed_plans")
    @patch("arknights_mower.views.mastery.get_all_plans")
    def test_plan_get_includes_failed_plans(
        self, get_all, get_failed, get_history, get_skill
    ):
        # #69：failed 计划要带给前端（含 failed_reason），不能"凭空消失"
        get_all.return_value = [
            {
                "id": 1,
                "char_id": "char_001",
                "char_name": "测试干员",
                "skill_index": 0,
                "skill_name": "一技能",
                "target_level": 1,
                "status": "idle",
                "priority": 0,
                "expires_at": None,
                "failed_reason": None,
            }
        ]
        get_failed.return_value = [
            {
                "id": 2,
                "char_id": "char_002",
                "char_name": "失败干员",
                "skill_index": 1,
                "skill_name": "二技能",
                "target_level": 2,
                "status": "failed",
                "priority": 0,
                "expires_at": None,
                "failed_reason": "材料不足",
            }
        ]
        get_history.return_value = []
        get_skill.return_value = {"characters": {}}

        response = self.client.get("/mastery-plan")
        self.assertEqual(response.status_code, 200)
        plans = response.get_json()["plans"]
        self.assertEqual([p["status"] for p in plans], ["idle", "failed"])
        failed = next(p for p in plans if p["status"] == "failed")
        self.assertEqual(failed["failed_reason"], "材料不足")
        self.assertEqual(failed["name"], "失败干员")


if __name__ == "__main__":
    unittest.main()
