import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock

# base_schedule 导入链（cultivate_depot→skland）会在 skland 模块加载时调用
# SecuritySm.get_d_id() 发网络请求（环境性 flake，与测试无关）。测试不涉及
# skland，预置 stub 挡住，避免单测依赖外网。
sys.modules.setdefault("arknights_mower.utils.skland", MagicMock())

from arknights_mower.solvers.base_schedule import BaseSchedulerSolver
from arknights_mower.utils.scene import Scene

choose_train = BaseSchedulerSolver.choose_train


def make_solver(scenes, scan_results, locked=False):
    """fake solver：脚本化场景 + 分次返回的训练室槽位扫描结果。

    复刻 tests/mastery_arranging_tests.py 的 fake solver 范式：
    用 MagicMock 替身驱动真实的 choose_train 逻辑，断言选人调用。

    locked=True：D4 锁定检测读到有效倒计时 → 训练位视为锁定。
    """
    solver = MagicMock()
    solver.scene.side_effect = list(scenes)
    solver.get_agent_from_room.side_effect = list(scan_results)

    def fake_find(res, *args, **kwargs):
        # 房间详情浮层常开；training_completed 模板不存在（否则 D4 会判锁定）
        if res == "training_completed":
            return None
        return True

    solver.find.side_effect = fake_find
    solver.train_scene.return_value = Scene.TRAIN_MAIN
    solver.double_read_time.return_value = (
        datetime.now().replace(year=2099) if locked else datetime.now()
    )
    solver.recog.w = 1920
    solver.recog.h = 1080
    solver.tasks = []
    solver.task = None
    return solver


class TestChooseTrainCurrentReplacement(unittest.TestCase):
    """#53 根因1：choose_train 的 Current 位置用替换后的实际干员名选人。

    修复前：INFRA_ARRANGE_ORDER 分支用 agents[idx]（可能是 'Current'）选人，
    'Current' 被当干员名 → 不点职业筛选 → 扫不到 → 触底 raise("重试一次") → failed。
    修复后：desired[idx] 是 scan 阶段替换后的真实干员名；agents[0]=="Current"
    的协助位视为保持原样，不进 select_targets，choose_agent 不再收到 'Current'。
    """

    def test_swap_trainer_keeps_assistant_and_swaps_real_name(self):
        """choose_train(['Current', '若叶睦'])：协助位不动，只换训练位（真实名）。"""
        solver = make_solver(
            scenes=[
                Scene.INFRA_DETAILS,
                Scene.INFRA_DETAILS,
                Scene.INFRA_ARRANGE_ORDER,
                Scene.INFRA_DETAILS,
            ],
            scan_results=[
                [{"agent": "褐果"}, {"agent": "桃金娘"}],
                [{"agent": "褐果"}, {"agent": "若叶睦"}],  # 换人后重扫：训练位已就位
            ],
        )
        choose_train(solver, ["Current", "若叶睦"])
        solver.choose_train_ope.assert_called_once_with("若叶睦")
        self.assertFalse(
            solver.choose_agent.called,
            "协助位 Current 应视为保持原样，不应触发 choose_agent",
        )

    def test_swap_assistant_picks_real_name(self):
        """choose_train(['夜莺', 'Current'])：idx0 换协助位走 choose_agent，传真实干员名。"""
        solver = make_solver(
            scenes=[
                Scene.INFRA_DETAILS,
                Scene.INFRA_DETAILS,
                Scene.INFRA_ARRANGE_ORDER,
                Scene.INFRA_DETAILS,
            ],
            scan_results=[
                [{"agent": "褐果"}, {"agent": "桃金娘"}],
                [{"agent": "夜莺"}, {"agent": "桃金娘"}],
            ],
        )
        choose_train(solver, ["夜莺", "Current"])
        solver.choose_agent.assert_called_once_with(["夜莺"], "train", True)
        self.assertFalse(
            solver.choose_train_ope.called,
            "idx1 Current 应视为保持原样（替换后与其 scan 相同），不应触发 choose_train_ope",
        )


class TestChooseTrainD4LockSkip(unittest.TestCase):
    """#59 D4：训练位锁定（🔴 训练中 / 🟡 待收取）时跳过 idx1 更换，不空转 2 分钟超时。"""

    def test_skip_locked_trainer_slot(self):
        solver = make_solver(
            scenes=[Scene.INFRA_DETAILS, Scene.INFRA_DETAILS],
            scan_results=[
                [{"agent": "褐果"}, {"agent": "桃金娘"}],
                [{"agent": "褐果"}, {"agent": "桃金娘"}],
            ],
            locked=True,
        )
        choose_train(solver, ["Current", "若叶睦"])
        self.assertFalse(
            solver.choose_train_ope.called,
            "训练位锁定时应跳过 idx1，不尝试更换锁定的训练干员",
        )
        self.assertFalse(solver.choose_agent.called, "协助位 Current 保持原样")

    def test_not_locked_still_swaps_trainer(self):
        solver = make_solver(
            scenes=[
                Scene.INFRA_DETAILS,
                Scene.INFRA_DETAILS,
                Scene.INFRA_ARRANGE_ORDER,
                Scene.INFRA_DETAILS,
            ],
            scan_results=[
                [{"agent": "褐果"}, {"agent": "桃金娘"}],
                [{"agent": "褐果"}, {"agent": "若叶睦"}],
            ],
            locked=False,
        )
        choose_train(solver, ["Current", "若叶睦"])
        solver.choose_train_ope.assert_called_once_with("若叶睦")


if __name__ == "__main__":
    unittest.main()
