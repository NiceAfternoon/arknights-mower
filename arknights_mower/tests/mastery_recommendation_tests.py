import unittest
from unittest.mock import patch

from arknights_mower.utils import mastery_recommendation as rec


def _recommendations(stages_achievable=(True, True, True), current_level=0):
    """构造 get_mastery_recommendations 返回值：单干员单技能（skill_index=1）。"""
    stages = [
        {
            "from_level": i + 7,
            "to_level": i + 8,
            "achievable": stages_achievable[i],
            "needed_materials": [],
            "missing_materials": [],
        }
        for i in range(3)
    ]
    return {
        "has_data": True,
        "operators": [
            {
                "char_id": "char_A",
                "recommendations": [
                    {
                        "skill_index": 1,
                        "current_level": current_level,
                        "stages": stages,
                    }
                ],
            }
        ],
    }


class TestMasteryMaterialsReady(unittest.TestCase):
    """§16.7 材料门控：开始训练前提 = 材料充足（仓库扫描确认），数据缺失/异常 → False。"""

    def setUp(self):
        rec._MATERIALS_CACHE.clear()
        rec._MATERIALS_CACHE.update({"ts": None, "mtime": None, "map": {}})

    def _ready(self, target, **kw):
        with patch.object(
            rec,
            "get_mastery_recommendations",
            return_value=_recommendations(**kw),
        ):
            return rec.mastery_materials_ready("char_A", 1, target)

    def test_full_chain_achievable(self):
        self.assertTrue(self._ready(3))

    def test_short_target_uses_prefix(self):
        # 目标专一：只要求第 0 段材料（专三段材料不足不影响）
        self.assertTrue(self._ready(1, stages_achievable=(True, False, False)))

    def test_insufficient_blocked(self):
        self.assertFalse(self._ready(3, stages_achievable=(True, True, False)))

    def test_current_at_target_no_materials_needed(self):
        self.assertTrue(self._ready(2, current_level=2))

    def test_already_m3_no_materials_needed(self):
        # current_level==3 的技能被 get_mastery_recommendations 跳过、不在推荐表 →
        # 从 cultivate.json 补档位：>= target → 无需材料（否则 ⑥ 已到target 被门控永久挡住）
        with (
            patch.object(
                rec, "get_mastery_recommendations", return_value=_recommendations()
            ),
            patch.object(rec, "_iter_skill_levels", return_value=[("char_A", 1, 3)]),
        ):
            self.assertTrue(rec.mastery_materials_ready("char_A", 1, 3))
            self.assertTrue(rec.mastery_materials_ready("char_A", 1, 1))

    def test_cache_invalidates_on_cultivate_mtime_change(self):
        # 仓库扫描刷新 cultivate.json（mtime 变）→ 缓存立即失效，不等 TTL
        with patch.object(
            rec,
            "get_mastery_recommendations",
            return_value=_recommendations(stages_achievable=(True, True, False)),
        ):
            self.assertFalse(rec.mastery_materials_ready("char_A", 1, 3))
        with (
            patch.object(rec, "get_mastery_recommendations", return_value=_recommendations()),
            patch("os.path.getmtime", return_value=999999),
        ):
            self.assertTrue(rec.mastery_materials_ready("char_A", 1, 3))

    def test_no_data_returns_false(self):
        with patch.object(
            rec,
            "get_mastery_recommendations",
            return_value={"has_data": False, "operators": []},
        ):
            self.assertFalse(rec.mastery_materials_ready("char_A", 1, 3))

    def test_unknown_operator_false(self):
        with patch.object(rec, "get_mastery_recommendations", return_value=_recommendations()):
            self.assertFalse(rec.mastery_materials_ready("char_ZZZ", 1, 3))

    def test_unknown_skill_false(self):
        with patch.object(rec, "get_mastery_recommendations", return_value=_recommendations()):
            self.assertFalse(rec.mastery_materials_ready("char_A", 0, 3))


if __name__ == "__main__":
    unittest.main()
