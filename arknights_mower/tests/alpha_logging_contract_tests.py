"""fork/alpha 合入日志的增量合同测试。

这些日志不属于 #48 冻结 ledger；它们按 doc/logging-constraints.md 的同一合同审计。
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from arknights_mower.solvers import mastery, mastery_reader, record


def make_plan(**overrides):
    plan = {
        "id": 7,
        "char_id": "char_test",
        "char_name": "测试干员",
        "skill_index": 1,
        "skill_name": "二技能·测试技能",
        "target_level": 3,
        "status": "training",
        "priority": 1,
    }
    plan.update(overrides)
    return plan


class TestMasteryRoomReadLogging(unittest.TestCase):
    def test_first_ocr_success_is_silent(self):
        panel = mastery_reader.RoomPanel()
        with (
            patch.object(mastery_reader, "_safe_read_panel", return_value=panel),
            patch.object(mastery_reader, "_classify_panel", return_value="training"),
            patch.object(mastery_reader.logger, "warning") as warning,
        ):
            room = mastery_reader._retry_ocr(MagicMock())

        self.assertEqual(room.state, "training")
        warning.assert_not_called()

    def test_ocr_retry_recovery_emits_one_summary(self):
        panel = mastery_reader.RoomPanel()
        with (
            patch.object(mastery_reader, "_safe_read_panel", return_value=panel),
            patch.object(
                mastery_reader,
                "_classify_panel",
                side_effect=["ocr_fail", "ocr_fail", "training"],
            ),
            patch.object(mastery_reader.logger, "warning") as warning,
        ):
            room = mastery_reader._retry_ocr(MagicMock())

        self.assertEqual(room.state, "training")
        warning.assert_called_once_with(
            "训练室识别重试后恢复：operation=mastery_room_read "
            "result=recovered retries=3"
        )

    def test_ocr_retry_exhaustion_emits_one_summary(self):
        panel = mastery_reader.RoomPanel()
        with (
            patch.object(mastery_reader, "_safe_read_panel", return_value=panel),
            patch.object(mastery_reader, "_classify_panel", return_value="ocr_fail"),
            patch.object(mastery_reader.logger, "warning") as warning,
        ):
            room = mastery_reader._retry_ocr(MagicMock())

        self.assertTrue(room.read_failed)
        warning.assert_called_once_with(
            "训练室识别重试已耗尽，按训练中保守处理：operation=mastery_room_read "
            "result=exhausted retries=5 fallback=training"
        )

    def test_unchanged_training_state_is_silent(self):
        plan = make_plan()
        room = mastery_reader.RoomState(
            "training",
            mastery_reader.RoomPanel(
                operator_name="测试干员",
                skill_name="测试技能",
                countdown_state="active",
            ),
        )
        with (
            patch.object(mastery_reader, "_match_plan", return_value=plan),
            patch.object(mastery_reader, "_can_adopt_expiry", return_value=True),
            patch.object(mastery_reader, "_refresh_training_plan"),
            patch.object(mastery_reader.logger, "info") as info,
        ):
            mastery_reader._reconcile_training(MagicMock(), room, plan, [plan])

        info.assert_not_called()


class TestMasterySwapLogging(unittest.TestCase):
    def test_retry_recovery_emits_one_warning(self):
        solver = MagicMock()
        plan = make_plan()
        with (
            patch.object(mastery, "_swap_still_worthwhile", return_value=True),
            patch.object(mastery, "_try_swap", side_effect=[False, True]),
            patch.object(mastery.logger, "warning") as warning,
            patch.object(mastery.logger, "error") as error,
        ):
            result = mastery._retry_swap_in_place(solver, plan, {}, "减半干员")

        self.assertTrue(result)
        warning.assert_called_once_with(
            "专精协助位换人重试后恢复：operation=mastery_support_swap "
            "plan_id=7 result=recovered retries=2"
        )
        error.assert_not_called()

    def test_retry_exhaustion_emits_one_error(self):
        solver = MagicMock()
        plan = make_plan()
        with (
            patch.object(mastery, "_swap_still_worthwhile", return_value=True),
            patch.object(mastery, "_try_swap", return_value=False),
            patch.object(mastery.logger, "warning") as warning,
            patch.object(mastery.logger, "error") as error,
        ):
            result = mastery._retry_swap_in_place(solver, plan, {}, "减半干员")

        self.assertFalse(result)
        warning.assert_not_called()
        error.assert_called_once_with(
            "专精协助位换人重试已耗尽：operation=mastery_support_swap plan_id=7 "
            f"result=exhausted retries={mastery.SWAP_RETRY_LIMIT}"
        )


class TestRoutinePersistenceLogging(unittest.TestCase):
    def test_trading_save_success_is_silent(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.fetchone.return_value = (0,)
        context = MagicMock()
        context.__enter__.return_value = connection
        result = MagicMock(
            time=datetime(2026, 8, 17, tzinfo=timezone.utc),
            buff="龙舌兰",
            price=1000,
        )
        wrapped = record.save_trading_info(lambda *args, **kwargs: result)

        with (
            patch.object(record, "_conn", return_value=context),
            patch.object(record.logger, "info") as info,
        ):
            self.assertIs(wrapped(None, None, result.time), result)

        info.assert_not_called()

    def test_duplicate_trading_record_is_silent(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.fetchone.return_value = (1,)
        context = MagicMock()
        context.__enter__.return_value = connection
        wrapped = record.save_trading_info(lambda *args, **kwargs: object())

        with (
            patch.object(record, "_conn", return_value=context),
            patch.object(record.logger, "debug") as debug,
        ):
            self.assertIsNone(
                wrapped(None, None, datetime(2026, 8, 17, tzinfo=timezone.utc))
            )

        debug.assert_not_called()
