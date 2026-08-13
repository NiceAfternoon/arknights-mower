import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np

import arknights_mower.solvers.mastery as mastery
from arknights_mower.solvers import mastery_reader
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

    @staticmethod
    def _seq(scenes, fallback=Scene.TRAIN_SKILL_SELECT):
        """按列表喂场景，耗尽后停在 fallback。"""

        def _next():
            return scenes.pop(0) if scenes else fallback

        return _next

    def make_solver(
        self,
        scene=None,
        scenes=None,
        scene_fallback=Scene.TRAIN_SKILL_SELECT,
        execute_time=None,
        slots=None,
        choose_train=None,
    ):
        solver = MagicMock()
        if scenes is not None:
            solver.train_scene.side_effect = self._seq(scenes, scene_fallback)
        else:
            solver.train_scene.return_value = scene
        solver.double_read_time.return_value = execute_time if execute_time else START
        solver.get_agent_from_room.return_value = (
            slots if slots else [{"agent": ""}, {"agent": ""}]
        )
        if choose_train is not None:
            solver.choose_train.side_effect = choose_train
        solver.read_screen.return_value = "[测试干员]测试技能"
        solver.tasks = []
        solver.task = None
        solver.recog.w = 1920
        solver.recog.h = 1080
        solver.recog.img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        solver.recog.update = MagicMock()
        return solver

    # --- 死循环回归：TRAIN_SKILL_SELECT 无限停留 ---
    def test_freeze_skill_select_does_not_infinite_loop(self):
        """#19 修复前 TRAIN_SKILL_SELECT 分支无超时退出会永远循环。

        现在：经训练位确认进入 219 后若一直卡在 219（ctap 不导航），10 分钟
        deadline 后走统一超时出口 → 置 failed + back() 退出。时钟每轮推进，
        否则 `now() > deadline` 永不成立、测试会真的挂死。
        未确认身份的 219（误判的运行页）不走 deadline、立即保守退出——见
        test_misjudged_skill_select_no_identity_exits。
        """
        scenes = [
            Scene.TRAIN_MAIN,  # 读占用(无) → 读槽位(空) → back
            Scene.TRAIN_MAIN,  # 训练位已确认 → 点开技能选择页（身份确认）
            Scene.TRAIN_SKILL_SELECT,  # 读档位(0) → ctap（不导航，卡住）
        ]
        solver = self.make_solver(scenes=scenes)
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
        # 场景推进：TRAIN_MAIN(读槽位发现坐错人→换人→back) → TRAIN_MAIN(训练位已确认
        # → 点开技能选择页) → TRAIN_SKILL_SELECT(读档位→ctap，此后停 219，推进时钟收敛)
        solver = self.make_solver(
            scenes=[
                Scene.TRAIN_MAIN,
                Scene.TRAIN_MAIN,
                Scene.TRAIN_SKILL_SELECT,
            ],
            slots=[{"agent": ""}, {"agent": "错误干员"}],
        )
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
            # 前两次（读占用×2）无倒计时；第三次起是确认流程（第一次无倒计时继续等，
            # 第二次读到有效倒计时确认开始）——219 不再读倒计时（#72）
            return START if read_count["n"] <= 3 else START + timedelta(hours=2)

        scenes = [
            Scene.TRAIN_MAIN,  # 迭代1：读倒计时(无) → 读槽位(空) → back
            Scene.TRAIN_MAIN,  # 迭代2：tap 选择技能（身份确认）
            Scene.TRAIN_SKILL_SELECT,  # 迭代3：读档位(0) → ctap 技能
            Scene.TRAIN_SKILL_UPGRADE,  # 迭代4：tap 确认 → 进入确认流程
        ]
        solver = self.make_solver(scenes=scenes, scene_fallback=Scene.TRAIN_MAIN)
        solver.double_read_time.side_effect = fake_double_read
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
        solver.read_screen.return_value = "[测试干员]测试技能"
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
        solver.read_screen.return_value = "[测试干员]测试技能"
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

    # --- #72：运行中的训练页被误判成 219（未经过训练位确认）→ 不数星星、不点技能行 ---
    def test_misjudged_skill_select_no_identity_exits(self):
        """误判的 219：倒计时、面板文字都不可读（真技能选择页读不到主面板区域）
        → 数星星前无身份确认，星星可能误读非零值（误开训练/误判完成）→ 保持 idle
        重排退出，绝不 ctap/tap。这是 #72 的核心红测试（旧代码在此会 ctap）。"""
        solver = self.make_solver(
            scene=Scene.TRAIN_SKILL_SELECT,
            execute_time=START,  # 误判页上倒计时不可读（读不到返回 now）
        )
        solver.read_screen.return_value = ""  # 真技能选择页读不到面板文字
        plan = make_plan()
        _, upd = self.run_arranging(solver, plan)

        idle_calls = [c for c in upd.call_args_list if c.args[1] == "idle"]
        self.assertTrue(idle_calls, "误判 219 应保持 idle 重排")
        self.assertTrue(solver.back.called, "应退出训练室")
        self.assertEqual(len(solver.tasks), 1, "应重排一条 SKILL_UPGRADE 任务")
        self.assertEqual(
            solver.tasks[0].time,
            START + mastery.ARRANGING_RETRY_BUFFER,
        )
        self.assertFalse(solver.ctap.called, "未确认身份时不应数星星/点技能行")
        self.assertFalse(solver.tap.called, "未确认身份时不应点技能选择按钮")

    def test_misjudged_skill_select_with_readable_countdown_exits(self):
        """误判的 219 即使倒计时可读（物理上仍是运行页）也因未确认身份而保守退出。

        旧守卫靠"在 219 上读主面板倒计时/面板当探针"判占用（#69/B4）；#72 起 219
        不再读主面板区域，身份确认只认 TRAIN_MAIN 训练位校验这一步，与倒计时是否
        可读无关（#72 验收 2：219 分支不再读主面板区域当探针）。"""
        solver = self.make_solver(
            scene=Scene.TRAIN_SKILL_SELECT,
            execute_time=START + timedelta(hours=2),  # 旧守卫能读到未来倒计时
        )
        plan = make_plan()
        _, upd = self.run_arranging(solver, plan)

        idle_calls = [c for c in upd.call_args_list if c.args[1] == "idle"]
        self.assertTrue(idle_calls, "误判 219 应保持 idle 重排")
        self.assertTrue(solver.back.called, "应退出训练室")
        self.assertEqual(
            solver.tasks[0].time,
            START + mastery.ARRANGING_RETRY_BUFFER,
        )
        self.assertFalse(solver.ctap.called, "未确认身份时不应点技能行")
        self.assertFalse(solver.tap.called, "未确认身份时不应点技能选择按钮")

    # --- #70/B5：已到target档位读失败保守化 ---
    def test_unreadable_tier_no_blind_start(self):
        """经训练位确认进入真 219（身份已确认；TRAIN_MAIN 上的技能选择 tap 属正常导航），
        档位读失败（None，无法判是否已到 target）→ 保持 idle 重排退出，绝不点技能行。"""
        solver = self.make_solver(
            scenes=[
                Scene.TRAIN_MAIN,  # 读占用(无) → 读槽位(空) → back
                Scene.TRAIN_MAIN,  # 训练位已确认 → 点开技能选择页（身份确认）
                Scene.TRAIN_SKILL_SELECT,  # 读档位 → 失败（img=None）
            ]
        )
        solver.recog.img = None  # 档位读取失败
        plan = make_plan()
        _, upd = self.run_arranging(solver, plan)

        idle_calls = [c for c in upd.call_args_list if c.args[1] == "idle"]
        self.assertTrue(idle_calls, "档位不可读时应保持 idle 重排")
        self.assertTrue(solver.back.called, "应退出训练室")
        self.assertEqual(len(solver.tasks), 1, "应重排一条 SKILL_UPGRADE 任务")
        self.assertEqual(
            solver.tasks[0].time,
            START + mastery.ARRANGING_RETRY_BUFFER,
        )
        self.assertFalse(solver.ctap.called, "档位不可读时不应点技能行")

    def test_read_tier_zero_proceeds_to_start(self):
        """经训练位确认进入真 219，档位读到 0（明确低于 target）→ 正常开始流程
        （点技能行），不保守退出。"""
        solver = self.make_solver(
            scenes=[
                Scene.TRAIN_MAIN,
                Scene.TRAIN_MAIN,
                Scene.TRAIN_SKILL_SELECT,
            ]
        )
        # recog.img 为全零画布 → _read_slot_mastery_tier 返回 0（明确未专精）
        plan = make_plan(target_level=3)
        self.run_arranging(solver, plan, advance=timedelta(minutes=1))

        self.assertTrue(solver.ctap.called, "档位=0 明确低于 target 时应继续点技能行")

    def test_skill_select_tier_at_target_completes(self):
        """经训练位确认进入真 219，目标槽档位读到 ≥ target → 判 completed（#63/#67
        已到target检测），不重复开始训练。"""
        solver = self.make_solver(
            scenes=[
                Scene.TRAIN_MAIN,
                Scene.TRAIN_MAIN,
                Scene.TRAIN_SKILL_SELECT,
            ]
        )
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        # 技能2（skill_index=1）三颗星全亮 → 档位 3 ≥ target 3
        for (x0, y0), (x1, y1) in mastery_reader.SKILL_SLOT_PIPS[1]:
            img[y0:y1, x0:x1] = 255
        solver.recog.img = img
        plan = make_plan(skill_index=1, target_level=3)
        with (
            patch.object(mastery, "datetime", FixedDateTime),
            patch("arknights_mower.utils.mastery_db.update_plan_status") as upd,
            patch(
                "arknights_mower.utils.mastery_db.get_next_idle_plan",
                return_value=None,
            ),
            patch("arknights_mower.utils.email.send_message"),
        ):
            mastery._start_new_training(solver, plan)

        completed_calls = [c for c in upd.call_args_list if c.args[1] == "completed"]
        self.assertTrue(completed_calls, "档位≥target 应判完成")
        self.assertTrue(solver.back.called, "完成后应退出训练室")
        self.assertFalse(solver.ctap.called, "已完成不应点技能行")

    # --- #69/B3：训练位坐错人 + 换人失败 → failed + 一次 ERROR 通知（全流程） ---
    def test_arranging_swap_failure_sends_error(self):
        """换人失败（choose_train 抛异常，含 D4 训练位锁定）→ 计划 failed + 一次 ERROR。"""

        def boom(*args, **kwargs):
            raise Exception("训练位被锁定，无法换入指定干员")

        solver = self.make_solver(
            scene=Scene.TRAIN_MAIN,
            slots=[{"agent": ""}, {"agent": "错误干员"}],
            choose_train=boom,
        )
        plan = make_plan()
        with (
            patch.object(mastery, "datetime", FixedDateTime),
            patch("arknights_mower.utils.mastery_db.update_plan_status") as upd,
            patch("arknights_mower.utils.email.send_message") as send,
        ):
            mastery._start_new_training(solver, plan)

        failed_calls = [c for c in upd.call_args_list if c.args[1] == "failed"]
        self.assertTrue(failed_calls, "换人失败应标记 failed")
        self.assertTrue(solver.back.called, "失败后应退出训练室")
        self.assertTrue(
            any(c.kwargs.get("level") == "ERROR" for c in send.call_args_list),
            "换人失败应发一次 ERROR 通知",
        )

    # --- #69/B2：确认开始读到的面板与计划不符 → 计划 failed，绝不写 training ---
    def test_confirm_rejects_wrong_operator_panel(self):
        """确认时读到陌生干员的面板 → 不写 training，标记 failed + 一次 ERROR 通知。"""
        solver = self.make_solver(
            scene=Scene.TRAIN_MAIN,
            execute_time=START + timedelta(hours=2),
        )
        solver.read_screen.return_value = "[错误干员]其他技能"
        plan = make_plan()
        with (
            patch.object(mastery, "datetime", FixedDateTime),
            patch("arknights_mower.utils.mastery_db.update_plan_status") as upd,
            patch("arknights_mower.utils.email.send_message") as send,
        ):
            result = mastery._confirm_training_started(
                solver, plan, START + timedelta(minutes=10)
            )

        self.assertEqual(result, "failed")
        training_calls = [c for c in upd.call_args_list if c.args[1] == "training"]
        self.assertFalse(training_calls, "面板与计划不符时不得写 training")
        failed_calls = [c for c in upd.call_args_list if c.args[1] == "failed"]
        self.assertTrue(failed_calls, "应标记 failed")
        self.assertTrue(solver.back.called, "失败后应退出训练室")
        self.assertTrue(
            any(c.kwargs.get("level") == "ERROR" for c in send.call_args_list),
            "应发一次 ERROR 通知",
        )

    def test_confirm_unreadable_panel_does_not_write(self):
        """倒计时有效但面板干员名不可读（OCR 失败）→ 不写 training，直到超时。"""

        class _Advance(FixedDateTime):
            @classmethod
            def now(cls, tz=None):
                FixedDateTime.now_value += timedelta(minutes=1)
                if tz is not None:
                    return FixedDateTime.now_value.replace(tzinfo=tz)
                return FixedDateTime.now_value

        solver = self.make_solver(
            scene=Scene.TRAIN_MAIN,
            execute_time=START + timedelta(hours=2),
        )
        solver.read_screen.return_value = ""
        plan = make_plan()
        with (
            patch.object(mastery, "datetime", _Advance),
            patch("arknights_mower.utils.mastery_db.update_plan_status") as upd,
            patch("arknights_mower.utils.email.send_message"),
        ):
            result = mastery._confirm_training_started(
                solver, plan, START + timedelta(minutes=10)
            )

        self.assertEqual(result, "timeout")
        training_calls = [c for c in upd.call_args_list if c.args[1] == "training"]
        self.assertFalse(training_calls, "面板不可读时不得把陌生人的倒计时写进计划")

    def test_arranging_no_wrong_start_on_mismatch(self):
        """#69/B2 全流程（#72 真实页面模型）：219 经训练位确认进入、不读面板文字，
        确认页读到陌生干员面板 → 计划 failed，绝不写 training。"""
        reads = iter([START, START, START + timedelta(hours=2)])

        def fake_double_read(*args, **kwargs):
            return next(reads, START)

        scenes = [
            Scene.TRAIN_MAIN,  # 读占用(无) → 读槽位(空) → back
            Scene.TRAIN_MAIN,  # tap 选择技能（身份确认）
            Scene.TRAIN_SKILL_SELECT,  # 读档位(0) → ctap 技能
            Scene.TRAIN_SKILL_UPGRADE,  # tap 确认 → 确认页读到陌生干员面板
        ]
        solver = self.make_solver(scenes=scenes, scene_fallback=Scene.TRAIN_MAIN)
        solver.double_read_time.side_effect = fake_double_read
        solver.read_screen.return_value = "[错误干员]其他技能"  # 真 219 不读面板；确认页才读
        plan = make_plan()
        _, upd = self.run_arranging(solver, plan)

        training_calls = [c for c in upd.call_args_list if c.args[1] == "training"]
        failed_calls = [c for c in upd.call_args_list if c.args[1] == "failed"]
        self.assertFalse(training_calls, "陌生干员面板下不得写 training")
        self.assertTrue(failed_calls, "应标记 failed")


class TestMasteryMailOperatorName(unittest.TestCase):
    """#53 根因3：邮件/日志文案用干员名（char_name，回退 get_char_name），不再用技能名/char_id。"""

    def setUp(self):
        FixedDateTime.now_value = START

    def make_solver(self, panel_text="[测试干员]测试技能"):
        solver = MagicMock()
        solver.train_scene.return_value = Scene.TRAIN_MAIN
        solver.double_read_time.return_value = START + timedelta(hours=2)
        solver.read_screen.return_value = panel_text
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
        # 面板名用 char_id（char_name 为 NULL 时的匹配依据），邮件文案回退 get_char_name
        solver = self.make_solver(panel_text="[char_test]测试技能")
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
