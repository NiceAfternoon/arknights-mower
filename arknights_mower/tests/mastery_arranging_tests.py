import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import arknights_mower.solvers.mastery as mastery
from arknights_mower.utils.scene import Scene

START = datetime(2026, 7, 31, 12, 0, 0)


def make_plan(**overrides):
    plan = {
        "id": 1,
        "char_id": "char_test",
        "char_name": "测试干员",
        "skill_index": 1,  # 技能2
        "skill_name": "测试技能",
        "target_level": 3,
        "status": "idle",
    }
    plan.update(overrides)
    return plan


class FixedDateTime(datetime):
    """冻结的假时钟，替换 mastery 模块的 datetime。"""

    now_value = START

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return cls.now_value.replace(tzinfo=tz)
        return cls.now_value


class TestArrangingConvergence(unittest.TestCase):
    """#18 模拟场景测试：fake solver 驱动真实 _start_new_training，断言有限步内收敛。

    _start_new_training 内 `from mastery_db import update_plan_status` 是函数体内局部
    import，因此要 patch 源模块 mastery_db / email，而非 mastery 模块本身。
    """

    def setUp(self):
        FixedDateTime.now_value = START

    def run_arranging(self, solver, plan, advance=timedelta(0)):
        """跑 _start_new_training，返回 (solver, update_plan_status mock)。

        advance：每轮 now() 额外前跳的时长。freeze 测试传 timedelta(minutes=1)
        让 10 分钟 deadline 几秒内可触发；其余场景传 0（冻结时钟）即可。
        """

        class Clock(FixedDateTime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    FixedDateTime.now_value += advance
                    return FixedDateTime.now_value
                return FixedDateTime.now_value.replace(tzinfo=tz)

        clock = Clock if advance else FixedDateTime
        with (
            patch.object(mastery, "datetime", clock),
            patch("arknights_mower.utils.mastery_db.update_plan_status") as upd,
            patch("arknights_mower.utils.email.send_message"),
        ):
            mastery._start_new_training(solver, plan)
        return solver, upd

    def make_solver(
        self, scene=None, scenes=None, execute_time=None, slots=None, choose_train=None
    ):
        solver = MagicMock()
        if scenes is not None:
            solver.train_scene.side_effect = list(scenes)
        else:
            solver.train_scene.return_value = scene
        solver.double_read_time.return_value = execute_time if execute_time else START
        solver.get_agent_from_room.return_value = (
            slots if slots else [{"agent": ""}, {"agent": ""}]
        )
        if choose_train is not None:
            solver.choose_train.side_effect = choose_train
        solver.tasks = []
        solver.task = None
        solver.recog.w = 1920
        solver.recog.h = 1080
        return solver

    # --- 死循环回归：TRAIN_SKILL_SELECT 无限停留 ---
    def test_freeze_skill_select_does_not_infinite_loop(self):
        """#19 修复前 TRAIN_SKILL_SELECT 分支无超时退出会永远循环。

        现在应：10 分钟 deadline 后走统一超时出口 → 置 failed + back() 退出。
        时钟每轮推进，否则 `now() > deadline` 永不成立、测试会真的挂死。
        """
        solver = self.make_solver(scene=Scene.TRAIN_SKILL_SELECT)
        plan = make_plan()
        _, upd = self.run_arranging(solver, plan, advance=timedelta(minutes=1))

        self.assertTrue(solver.back.called, "超时后应退出训练室")
        args = upd.call_args[0]
        self.assertEqual(args[0], 1)
        self.assertEqual(args[1], "failed")
        self.assertIn("超时", upd.call_args[1]["failed_reason"])

    # --- 训练室被占用：有倒计时 → idle + 重排 + 退出 ---
    def test_occupied_room_reschedules_and_exits(self):
        execute_time = START + timedelta(hours=2)
        solver = self.make_solver(scene=Scene.TRAIN_MAIN, execute_time=execute_time)
        plan = make_plan()
        _, upd = self.run_arranging(solver, plan)

        self.assertEqual(upd.call_args[0][1], "idle")
        self.assertTrue(solver.back.called)
        self.assertEqual(len(solver.tasks), 1)
        self.assertEqual(
            solver.tasks[0].time, execute_time + mastery.ARRANGING_RETRY_BUFFER
        )
        self.assertFalse(solver.tap.called, "占用时不应盲点选择技能")

    # --- 无倒计时 + 训练位坐错人 → choose_train 换人 ---
    def test_wrong_operator_triggers_swap(self):
        # 场景推进：TRAIN_MAIN(读槽位发现坐错人→换人→back) → TRAIN_SKILL_SELECT(点技能)
        # 此后停留技能选择页，靠推进时钟触发 deadline 让测试收敛
        scenes = [
            Scene.TRAIN_MAIN,
            Scene.TRAIN_SKILL_SELECT,
        ]

        def scene_seq():
            return scenes[0] if len(scenes) == 1 else scenes.pop(0)

        solver = MagicMock()
        solver.train_scene.side_effect = scene_seq
        solver.double_read_time.return_value = START
        solver.get_agent_from_room.return_value = [{"agent": ""}, {"agent": "错误干员"}]
        solver.tasks = []
        solver.task = None
        solver.recog.w = 1920
        solver.recog.h = 1080
        plan = make_plan()
        self.run_arranging(solver, plan, advance=timedelta(minutes=1))
        solver.choose_train.assert_called()
        self.assertEqual(solver.choose_train.call_args[0][0], ["Current", "测试干员"])

    # --- 换人失败 → failed + 退出 ---
    def test_swap_failure_marks_failed(self):
        def boom(*args, **kwargs):
            raise Exception("选人流程超时")

        solver = self.make_solver(
            scene=Scene.TRAIN_MAIN,
            slots=[{"agent": ""}, {"agent": "错误干员"}],
            choose_train=boom,
        )
        plan = make_plan()
        _, upd = self.run_arranging(solver, plan)
        args = upd.call_args[0]
        self.assertEqual(args[0], 1)
        self.assertEqual(args[1], "failed")
        self.assertTrue(solver.back.called)

    # --- 空闲训练室 → 正常开始 ---
    def test_free_room_starts_normally(self):
        read_count = {"n": 0}

        def fake_double_read(*args, **kwargs):
            read_count["n"] += 1
            # 前两次（读占用、读槽位）无倒计时；确认流程读到有效倒计时
            return START if read_count["n"] <= 2 else START + timedelta(hours=2)

        scenes = [
            Scene.TRAIN_MAIN,  # 迭代1：读倒计时(无) → 读槽位(空) → back
            Scene.TRAIN_MAIN,  # 迭代2：tap 选择技能
            Scene.TRAIN_SKILL_SELECT,  # 迭代3：ctap 技能
            Scene.TRAIN_SKILL_UPGRADE,  # 迭代4：tap 确认 → 进入确认流程
        ]

        def scene_seq():
            return scenes.pop(0) if scenes else Scene.TRAIN_MAIN

        solver = MagicMock()
        solver.train_scene.side_effect = scene_seq
        solver.double_read_time.side_effect = fake_double_read
        solver.get_agent_from_room.return_value = [{"agent": ""}, {"agent": ""}]
        solver.tasks = []
        solver.task = None
        solver.recog.w = 1920
        solver.recog.h = 1080
        plan = make_plan()
        _, upd = self.run_arranging(solver, plan)

        training_calls = [c for c in upd.call_args_list if c.args[1] == "training"]
        self.assertTrue(training_calls, "正常开始后应转入 training 状态")

    # --- 技能升级页确认按钮：必须用 skill_confirm 模板定位，不用旧坐标 ---
    def test_upgrade_confirm_taps_skill_confirm_position(self):
        """#53 实机：升级确认按钮在 (1574,896)-(1870,968)，旧坐标 (0.87w,0.9h)=(1670,972)
        会点到按钮下方、关掉弹窗退回技能选择页死循环。确认必须点 skill_confirm 按钮中心。
        """
        skill_confirm_pos = ((1563, 832), (1880, 1048))  # find 返回的可点区域
        solver = MagicMock()
        solver.find.return_value = skill_confirm_pos
        solver.train_scene.side_effect = [
            Scene.TRAIN_SKILL_UPGRADE,
            Scene.TRAIN_MAIN,
        ]
        solver.double_read_time.return_value = START + timedelta(hours=2)
        solver.tasks = []
        solver.task = None
        solver.recog.w = 1920
        solver.recog.h = 1080
        plan = make_plan()
        with (
            patch.object(mastery, "datetime", FixedDateTime),
            patch("arknights_mower.utils.mastery_db.update_plan_status"),
            patch("arknights_mower.utils.email.send_message"),
            patch.object(mastery, "_arrange_support"),
            patch.object(mastery, "_schedule_swap_if_needed"),
            patch.object(mastery, "_schedule_collect"),
        ):
            mastery._start_new_training(solver, plan)
        tap_calls = [c.args[0] for c in solver.tap.call_args_list]
        self.assertIn(
            skill_confirm_pos, tap_calls, "确认按钮应该用 skill_confirm 模板位置点"
        )
        self.assertNotIn(
            (solver.recog.w * 0.87, solver.recog.h * 0.9),
            tap_calls,
            "不应再用会错过按钮的旧坐标 (0.87w, 0.9h)",
        )

    def test_confirm_then_read_countdown_on_skill_select(self):
        """#53 实机：确认升级后训练已开始，但运行页被识别成 TRAIN_SKILL_SELECT，
        此时也要能读到倒计时、确认训练开始（而不是一直等 TRAIN_MAIN 到超时）。
        """
        solver = MagicMock()
        solver.find.return_value = ((1563, 832), (1880, 1048))  # skill_confirm
        solver.train_scene.side_effect = [
            Scene.TRAIN_SKILL_UPGRADE,  # 确认页 → tap 确认
            Scene.TRAIN_SKILL_SELECT,  # 训练运行页（被误识别成选择技能页）
        ]
        solver.double_read_time.return_value = START + timedelta(hours=2)
        solver.tasks = []
        solver.task = None
        solver.recog.w = 1920
        solver.recog.h = 1080
        plan = make_plan()
        with (
            patch.object(mastery, "datetime", FixedDateTime),
            patch("arknights_mower.utils.mastery_db.update_plan_status") as upd,
            patch("arknights_mower.utils.email.send_message"),
            patch.object(mastery, "_arrange_support"),
            patch.object(mastery, "_schedule_swap_if_needed"),
            patch.object(mastery, "_schedule_collect"),
        ):
            mastery._start_new_training(solver, plan)
        training_calls = [c for c in upd.call_args_list if c.args[1] == "training"]
        self.assertTrue(
            training_calls, "在 TRAIN_SKILL_SELECT 上读到有效倒计时也应确认训练开始"
        )


class TestMasteryMailOperatorName(unittest.TestCase):
    """#53 根因3：邮件/日志文案用干员名（char_name，回退 get_char_name），不再用技能名/char_id。"""

    def setUp(self):
        FixedDateTime.now_value = START

    def make_solver(self):
        solver = MagicMock()
        solver.train_scene.return_value = Scene.TRAIN_MAIN
        solver.double_read_time.return_value = START + timedelta(hours=2)
        solver.tasks = []
        solver.task = None
        solver.recog.w = 1920
        solver.recog.h = 1080
        return solver

    def test_start_mail_uses_stored_char_name(self):
        solver = self.make_solver()
        plan = make_plan(char_name="测试干员")
        with (
            patch.object(mastery, "datetime", FixedDateTime),
            patch("arknights_mower.utils.mastery_db.update_plan_status"),
            patch("arknights_mower.utils.email.send_message") as send,
            patch.object(mastery, "_arrange_support"),
            patch.object(mastery, "_schedule_swap_if_needed"),
            patch.object(mastery, "_schedule_collect"),
        ):
            result = mastery._confirm_training_started(
                solver, plan, START + timedelta(minutes=10)
            )
        self.assertEqual(result, "started")
        msg = send.call_args[0][0]
        self.assertIn("测试干员", msg)
        self.assertNotIn("char_test", msg)

    def test_start_mail_falls_back_to_get_char_name(self):
        solver = self.make_solver()
        plan = make_plan(char_name=None)
        with (
            patch.object(mastery, "datetime", FixedDateTime),
            patch("arknights_mower.utils.mastery_db.update_plan_status"),
            patch("arknights_mower.utils.email.send_message") as send,
            patch.object(mastery, "_arrange_support"),
            patch.object(mastery, "_schedule_swap_if_needed"),
            patch.object(mastery, "_schedule_collect"),
            patch.object(mastery, "get_char_name", return_value="兜底干员") as gcn,
        ):
            result = mastery._confirm_training_started(
                solver, plan, START + timedelta(minutes=10)
            )
        self.assertEqual(result, "started")
        self.assertIn("兜底干员", send.call_args[0][0])
        gcn.assert_called_once_with("char_test")


if __name__ == "__main__":
    unittest.main()
