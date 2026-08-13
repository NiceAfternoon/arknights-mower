import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np

from arknights_mower.solvers import mastery_reader as reader
from arknights_mower.utils.scene import Scene
from arknights_mower.utils.skill_label import (
    format_skill_label,
    panel_skill_matches,
)

NOW = datetime(2026, 8, 1, 12, 0, 0)


def make_plan(**overrides):
    plan = {
        "id": 1,
        "char_id": "char_test",
        "char_name": "测试干员",
        "skill_index": 1,  # 技能2
        "skill_name": "二技能·测试技能",
        "target_level": 3,
        "status": "idle",
        "priority": 1,
    }
    plan.update(overrides)
    return plan


def make_panel(**overrides):
    panel = reader.RoomPanel(
        operator_name="测试干员",
        skill_name="测试技能",
        mastery_tier=2,
        countdown=datetime.now() + timedelta(hours=2),
    )
    panel.__dict__.update(overrides)
    return panel


def make_room(state="empty", **panel_kwargs):
    return reader.RoomState(state=state, panel=make_panel(**panel_kwargs))


class TestSkillLabel(unittest.TestCase):
    def test_canonical_format(self):
        self.assertEqual(format_skill_label(1, "飞翔瞪射"), "二技能·飞翔瞪射")
        self.assertEqual(format_skill_label(0, "冲锋号令·α型"), "一技能·冲锋号令·α型")

    def test_placeholder_fallback(self):
        self.assertEqual(format_skill_label(0, "技能1"), "技能1")
        self.assertEqual(format_skill_label(2, None), "技能3")

    def test_already_canonical_passthrough(self):
        self.assertEqual(format_skill_label(2, "二技能·飞翔瞪射"), "二技能·飞翔瞪射")

    def test_normalize_and_match(self):
        self.assertTrue(panel_skill_matches("飞翔瞪射", "二技能·飞翔瞪射"))
        self.assertTrue(panel_skill_matches("扫射模式", "一技能·扫射模式"))
        self.assertFalse(panel_skill_matches("过载模式", "二技能·扫射模式"))
        self.assertFalse(panel_skill_matches("", "二技能·飞翔瞪射"))
        # 长名截断（面板显示前缀）仍是包含匹配
        self.assertTrue(panel_skill_matches("秘杖", "二技能·秘杖·反重力模式"))
        # 分隔符归一化：・ vs ·
        self.assertTrue(panel_skill_matches("冲锋号令・α型", "一技能·冲锋号令·α型"))


class TestPanelParse(unittest.TestCase):
    def test_parse_bracketed(self):
        self.assertEqual(
            reader._parse_panel_text("[能天使]扫射模式"), ("能天使", "扫射模式")
        )

    def test_parse_no_bracket(self):
        self.assertEqual(reader._parse_panel_text("扫射模式"), ("", "扫射模式"))

    def test_parse_empty(self):
        self.assertEqual(reader._parse_panel_text(""), ("", ""))


class TestCountLitMainPanelIcons(unittest.TestCase):
    """主面板专精图标逐框判亮（MASTERY_ICON_PIPS）。"""

    def _canvas(self, lit_indexes):
        """构造 1080p 画布，按 lit_indexes 点亮主面板三颗星。"""
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        for i, ((x0, y0), (x1, y1)) in enumerate(reader.MASTERY_ICON_PIPS):
            color = (255, 200, 92) if i in lit_indexes else (0, 0, 0)
            img[y0:y1, x0:x1] = color
        return img

    def _solver(self, img):
        s = unittest.mock.MagicMock()
        s.recog.img = img
        return s

    def test_zero(self):
        self.assertEqual(reader._count_lit_mastery_icons(self._solver(self._canvas([]))), 0)

    def test_one_top(self):
        self.assertEqual(reader._count_lit_mastery_icons(self._solver(self._canvas([0]))), 1)

    def test_two_top_and_second(self):
        self.assertEqual(reader._count_lit_mastery_icons(self._solver(self._canvas([0, 1]))), 2)

    def test_three_all(self):
        self.assertEqual(reader._count_lit_mastery_icons(self._solver(self._canvas([0, 1, 2]))), 3)

    def test_no_img_zero(self):
        self.assertEqual(reader._count_lit_mastery_icons(self._solver(None)), 0)


def _draw_circle(img, cx, cy, r, color):
    """在 RGB numpy 图上画实心圆（技能选择页星形测试用）。"""
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    img[mask] = color


class TestReadSlotMasteryTier(unittest.TestCase):
    def _canvas(self, lit_indexes, skill_index=0):
        """构造覆盖该技能三颗星区域的画布，按 lit_indexes 画亮/灭圆。"""
        boxes = reader.SKILL_SLOT_PIPS[skill_index]
        img = np.zeros((900, 700, 3), dtype=np.uint8)
        for i, ((x0, y0), (x1, y1)) in enumerate(boxes):
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            r = (x1 - x0) * 0.44
            color = (255, 200, 92) if i in lit_indexes else (58, 64, 82)
            _draw_circle(img, cx, cy, r, color)
        return img

    def _solver(self, img):
        s = unittest.mock.MagicMock()
        s.recog.img = img
        return s

    def test_unknown_skill_returns_none(self):
        s = self._solver(self._canvas([]))
        self.assertIsNone(reader._read_slot_mastery_tier(s, 3))

    def test_no_img_returns_none(self):
        self.assertIsNone(reader._read_slot_mastery_tier(self._solver(None), 0))

    def test_tier_zero(self):
        tier = reader._read_slot_mastery_tier(self._solver(self._canvas([])), 0)
        self.assertEqual(tier, 0)

    def test_tier_one_top_lit(self):
        tier = reader._read_slot_mastery_tier(self._solver(self._canvas([0])), 0)
        self.assertEqual(tier, 1)

    def test_tier_two_top_and_second(self):
        tier = reader._read_slot_mastery_tier(self._solver(self._canvas([0, 1])), 0)
        self.assertEqual(tier, 2)

    def test_tier_three_all_lit(self):
        tier = reader._read_slot_mastery_tier(
            self._solver(self._canvas([0, 1, 2])), 0
        )
        self.assertEqual(tier, 3)

    def test_skill_two_uses_its_own_boxes(self):
        # 技能2（index 1）的三颗星位于不同 y，独立定位不应串到技能1
        tier = reader._read_slot_mastery_tier(
            self._solver(self._canvas([0, 1], skill_index=1)), 1
        )
        self.assertEqual(tier, 2)
        # 技能2 全亮时，技能1 区域保持空（各自独立）
        tier0 = reader._read_slot_mastery_tier(
            self._solver(self._canvas([0, 1], skill_index=1)), 0
        )
        self.assertEqual(tier0, 0)


class TestClassifyRoom(unittest.TestCase):
    def test_train_finish_is_waiting_collect(self):
        self.assertEqual(
            reader.classify_room_state(Scene.TRAIN_FINISH, None), "waiting_collect"
        )

    def test_main_with_countdown_training(self):
        self.assertEqual(
            reader.classify_room_state(
                Scene.TRAIN_MAIN, datetime.now() + timedelta(hours=1)
            ),
            "training",
        )

    def test_main_no_countdown_empty(self):
        self.assertEqual(reader.classify_room_state(Scene.TRAIN_MAIN, None), "empty")
        self.assertEqual(
            reader.classify_room_state(Scene.TRAIN_MAIN, datetime.now()), "empty"
        )

    def test_other_scene_conservative(self):
        self.assertEqual(
            reader.classify_room_state(Scene.TRAIN_SKILL_SELECT, None), "training"
        )
        self.assertEqual(reader.classify_room_state(Scene.UNKNOWN, None), "training")


class TestMatchPlan(unittest.TestCase):
    def test_match_by_operator_and_skill(self):
        room = make_room("training")
        plan = make_plan()
        self.assertEqual(reader._match_plan([plan], room), plan)

    def test_no_match_wrong_skill(self):
        room = make_room("training", skill_name="别的技能")
        plan = make_plan()
        self.assertIsNone(reader._match_plan([plan], room))

    def test_no_match_empty_operator(self):
        room = make_room("training", operator_name="")
        plan = make_plan()
        self.assertIsNone(reader._match_plan([plan], room))

    def test_match_falls_back_to_operator_when_skill_unreadable(self):
        room = make_room("training", skill_name="")
        plan = make_plan()
        self.assertEqual(reader._match_plan([plan], room), plan)

    def test_match_excludes_terminal(self):
        room = make_room("training")
        done = make_plan(status="completed")
        self.assertIsNone(reader._match_plan([done], room))


class TestReadRoomState(unittest.TestCase):
    """fake solver 驱动真实 read_room_state：进房读面板+倒计时+图标+分类。"""

    def _solver(
        self, countdown, panel_text="[测试干员]测试技能", tier_columns=(0, 1, 2)
    ):
        solver = MagicMock()
        solver.train_scene.side_effect = [Scene.TRAIN_MAIN]
        solver.double_read_time.return_value = countdown
        solver.read_screen.return_value = panel_text
        solver.find.side_effect = lambda res, *a, **k: (
            None if res == "training_completed" else MagicMock()
        )
        solver.enter_room = MagicMock()
        solver.recog.w = 1920
        solver.recog.h = 1080
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        (x0, y0), (x1, y1) = reader.MASTERY_ICON_REGION
        slot_w = (x1 - x0) // 3
        for col in tier_columns:
            img[y0:y1, x0 + col * slot_w : x0 + (col + 1) * slot_w] = 255
        solver.recog.img = img
        solver.recog.update = MagicMock()
        return solver

    def test_training_state_reads_panel(self):
        solver = self._solver(datetime.now() + timedelta(hours=2))
        room = reader.read_room_state(solver)
        self.assertEqual(room.state, "training")
        self.assertEqual(room.panel.operator_name, "测试干员")
        self.assertEqual(room.panel.skill_name, "测试技能")
        self.assertEqual(room.panel.mastery_tier, 3)

    def test_empty_state_when_no_countdown(self):
        solver = self._solver(datetime.now())
        room = reader.read_room_state(solver)
        self.assertEqual(room.state, "empty")

    def test_waiting_collect_when_finish_scene(self):
        solver = self._solver(datetime.now())
        solver.train_scene.side_effect = [Scene.TRAIN_FINISH]
        room = reader.read_room_state(solver)
        self.assertEqual(room.state, "waiting_collect")


class TestReconcileShort(unittest.TestCase):
    """reconcile_short：排班路径顺路短动作（不开始训练、不退出房间）。"""

    def test_training_consistent_updates_expiry_no_exit(self):
        solver = MagicMock()
        room = make_room("training")
        active = make_plan(status="training")
        with (
            patch(
                "arknights_mower.utils.mastery_db.get_active_plan", return_value=active
            ),
            patch(
                "arknights_mower.utils.mastery_db.get_all_plans", return_value=[active]
            ),
            patch.object(reader, "_update_expiry") as ue,
            patch.object(reader, "_collect_plan"),
        ):
            reader.reconcile_short(solver, room)
        ue.assert_called_once_with(solver, active, room)
        solver.back.assert_not_called()  # 退出由调用方（gate）负责

    def test_waiting_collect_collects_no_exit(self):
        solver = MagicMock()
        room = make_room("waiting_collect")
        plan = make_plan(status="training")
        with (
            patch(
                "arknights_mower.utils.mastery_db.get_active_plan", return_value=plan
            ),
            patch(
                "arknights_mower.utils.mastery_db.get_all_plans", return_value=[plan]
            ),
            patch.object(reader, "_collect_plan") as cp,
        ):
            reader.reconcile_short(solver, room)
        cp.assert_called_once()
        solver.back.assert_not_called()


class TestReconcileMatrix(unittest.TestCase):
    """#61 恢复矩阵核心分支：空房/训练中/待收取 × 各 DB 状态。"""

    def test_empty_room_starts_next_idle(self):
        solver = MagicMock()
        room = make_room("empty")
        with patch(
            "arknights_mower.utils.mastery_db.get_next_idle_plan",
            return_value=make_plan(),
        ) as g:
            plan, arrange_support = reader._reconcile(solver, room, None, [make_plan()])
        self.assertIs(plan, g.return_value)
        self.assertTrue(arrange_support, "空房新开始应正常安排协助位")

    def test_empty_room_with_active_resets_quietly(self):
        # 空房×training 计划：截图权威 → 静默重置 idle 重开，不误报「假记录」通知②
        solver = MagicMock()
        room = make_room("empty")
        active = make_plan(status="training")
        with (
            patch("arknights_mower.utils.mastery_db.update_plan_status") as upd,
            patch(
                "arknights_mower.utils.mastery_db.get_next_idle_plan", return_value=None
            ),
            patch.object(reader, "_reset_fake") as rf,
        ):
            reader._reconcile(solver, room, active, [active])
        rf.assert_not_called()
        upd.assert_called_once_with(1, "idle")

    def test_arranging_any_state_resets_idle(self):
        solver = MagicMock()
        for state in ("training", "waiting_collect", "empty"):
            room = make_room(state)
            active = make_plan(status="arranging")
            with patch.object(reader, "_reset_to_idle") as ri:
                reader._reconcile(solver, room, active, [active])
            ri.assert_called_once_with(solver, active)

    def test_training_consistent_updates_expiry(self):
        solver = MagicMock()
        room = make_room("training")
        active = make_plan(status="training")
        with patch.object(reader, "_update_expiry") as ue:
            reader._reconcile(solver, room, active, [active])
        ue.assert_called_once_with(solver, active, room)

    def test_training_inconsistent_resets_fake(self):
        solver = MagicMock()
        room = make_room("training", operator_name="别的干员")
        active = make_plan(status="training")
        with (
            patch.object(reader, "_reset_fake") as rf,
            patch.object(reader, "_notify_blocked"),
            patch.object(reader, "_wait_for_training"),
        ):
            plan, _ = reader._reconcile(solver, room, active, [active])
        rf.assert_called_once()
        self.assertIsNone(plan)

    def test_training_unreadable_panel_not_fake(self):
        # 干员名不可读（OCR 失败）时不判「假记录」重置，走静默更新过期时间
        solver = MagicMock()
        room = make_room("training", operator_name="")
        active = make_plan(status="training")
        with (
            patch.object(reader, "_reset_fake") as rf,
            patch.object(reader, "_update_expiry") as ue,
        ):
            reader._reconcile(solver, room, active, [active])
        rf.assert_not_called()
        ue.assert_called_once()

    def test_training_unreadable_no_notify_blocked(self):
        # 干员名不可读时不判计划外训练，不通知①
        solver = MagicMock()
        room = make_room("training", operator_name="")
        with (
            patch.object(reader, "_notify_blocked") as nb,
        ):
            reader._reconcile(solver, room, None, [])
        nb.assert_not_called()

    def test_training_idle_hit_waits(self):
        solver = MagicMock()
        room = make_room("training")
        idle_plan = make_plan()
        with patch.object(reader, "_wait_for_training") as wt:
            reader._reconcile(solver, room, None, [idle_plan])
        wt.assert_called_once_with(solver, room)

    def test_training_unmatched_notifies_blocked(self):
        solver = MagicMock()
        room = make_room("training", operator_name="路人")
        with (
            patch.object(reader, "_notify_blocked") as nb,
            patch.object(reader, "_wait_for_training"),
        ):
            reader._reconcile(solver, room, None, [])
        nb.assert_called_once_with(solver, room)

    def test_waiting_collect_matched_collects(self):
        solver = MagicMock()
        room = make_room("waiting_collect")
        plan = make_plan()
        with (
            patch.object(reader, "_collect_plan") as cp,
        ):
            reader._reconcile(solver, room, None, [plan])
        cp.assert_called_once()

    def test_waiting_collect_unmatched_silent(self):
        solver = MagicMock()
        room = make_room("waiting_collect", operator_name="路人")
        with (
            patch.object(reader, "_collect_silent") as cs,
            patch.object(reader, "_collect_plan"),
        ):
            reader._reconcile(solver, room, None, [])
        cs.assert_called_once()

    def test_collect_cascade_no_arrange_support(self):
        # 收集级联（waiting_collect 命中）→ arrange_support=False（减半守卫：
        # 跨「收取→下一次开始」边界不重排协助位）
        solver = MagicMock()
        room = make_room("waiting_collect")
        plan = make_plan()
        with patch.object(reader, "_collect_plan", return_value=make_plan(id=2)):
            start, arrange_support = reader._reconcile(solver, room, None, [plan])
        self.assertIsNotNone(start)
        self.assertFalse(arrange_support)


class TestCollectFlow(unittest.TestCase):
    def _solver(self, tier_img=None):
        solver = MagicMock()
        solver.recog.w = 1920
        solver.recog.h = 1080
        solver.recog.update = MagicMock()
        solver.recog.img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        # find 默认返回 None → 走兜底坐标；training_completed 也 None
        solver.find.return_value = None
        solver.train_scene.return_value = Scene.TRAIN_MAIN
        return solver

    def test_collect_flow_sends_no_mail_below_m3(self):
        solver = self._solver()
        panel = make_panel(mastery_tier=2)
        with (
            patch("arknights_mower.utils.email.send_message") as send,
            patch("arknights_mower.utils.mastery_db.should_notify", return_value=True),
        ):
            reader.collect_flow(solver, make_plan(), panel)
        send.assert_not_called()

    def test_collect_flow_sends_mail_at_m3(self):
        solver = self._solver()
        panel = make_panel(mastery_tier=3)
        with (
            patch("arknights_mower.utils.email.send_message") as send,
            patch("arknights_mower.utils.mastery_db.should_notify", return_value=True),
        ):
            reader.collect_flow(solver, make_plan(), panel)
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs["level"], "INFO")
        self.assertIsNotNone(send.call_args.kwargs["attach_image"])

    def test_collect_flow_m3_dedup(self):
        solver = self._solver()
        panel = make_panel(mastery_tier=3)
        with (
            patch("arknights_mower.utils.email.send_message") as send,
            patch("arknights_mower.utils.mastery_db.should_notify", return_value=False),
        ):
            reader.collect_flow(solver, make_plan(), panel)
        send.assert_not_called()

    def test_collect_flow_taps_finish_mark_fallback(self):
        solver = self._solver()
        with (
            patch("arknights_mower.utils.email.send_message"),
            patch("arknights_mower.utils.mastery_db.should_notify", return_value=True),
        ):
            reader.collect_flow(solver, make_plan(), make_panel())
        taps = [c.args[0] for c in solver.tap.call_args_list]
        self.assertIn((solver.recog.w * 0.05, solver.recog.h * 0.95), taps)
        self.assertIn((solver.recog.w * 0.5, solver.recog.h * 0.5), taps)
        # #61 流程第 8 步：点勾确认（confirm_train 模板或兜底坐标）
        self.assertIn((solver.recog.w * 0.5, solver.recog.h * 0.85), taps)

    def test_collect_flow_prefers_template(self):
        solver = self._solver()
        finish_pos = ((50, 900), (130, 980))
        solver.find.side_effect = lambda res, *a, **k: (
            finish_pos if res == "skill_collect_confirm" else None
        )
        with (
            patch("arknights_mower.utils.email.send_message"),
            patch("arknights_mower.utils.mastery_db.should_notify", return_value=True),
        ):
            reader.collect_flow(solver, make_plan(), make_panel())
        self.assertIn(finish_pos, [c.args[0] for c in solver.tap.call_args_list])


class TestReconcileAfterCollect(unittest.TestCase):
    def test_meets_target_completes_and_cascades(self):
        panel = make_panel(mastery_tier=3)
        plan = make_plan(target_level=3)
        next_plan = make_plan(id=2)
        with (
            patch("arknights_mower.utils.mastery_db.update_plan_status") as upd,
            patch(
                "arknights_mower.utils.mastery_db.get_next_idle_plan",
                return_value=next_plan,
            ),
        ):
            result = reader._reconcile_after_collect(MagicMock(), plan, panel)
        upd.assert_called_once_with(1, "completed")
        self.assertIs(result, next_plan)

    def test_below_target_continues_same_plan(self):
        panel = make_panel(mastery_tier=2)
        plan = make_plan(target_level=3)
        with (
            patch("arknights_mower.utils.mastery_db.update_plan_status") as upd,
            patch("arknights_mower.utils.mastery_db.get_next_idle_plan"),
        ):
            result = reader._reconcile_after_collect(MagicMock(), plan, panel)
        upd.assert_called_once_with(1, "idle")
        self.assertIs(result, plan)

    def test_above_target_collect_not_completed(self):
        # #67/B6：专二收取关掉专一计划 → 不得完成（档位高于目标时本次收取不属于该计划）
        panel = make_panel(mastery_tier=2)
        plan = make_plan(target_level=1)
        with (
            patch("arknights_mower.utils.mastery_db.update_plan_status") as upd,
            patch("arknights_mower.utils.mastery_db.get_next_idle_plan"),
        ):
            result = reader._reconcile_after_collect(MagicMock(), plan, panel)
        statuses = [c.args[1] for c in upd.call_args_list]
        self.assertNotIn("completed", statuses, "高于目标的收取不得把计划标记完成")
        upd.assert_called_once_with(1, "idle")
        self.assertIs(result, plan)

    def test_no_plan_returns_none(self):
        self.assertIsNone(
            reader._reconcile_after_collect(MagicMock(), None, make_panel())
        )


if __name__ == "__main__":
    unittest.main()
