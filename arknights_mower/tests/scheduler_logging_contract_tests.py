"""#50 调度日志、SQLite 投影与消费者的公开合同。"""

import importlib
import json
import logging
import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arknights_mower.agent.tools import analyze_missed_order as analyze_mod
from arknights_mower.solvers import record
from arknights_mower.utils import operators as operators_mod
from arknights_mower.utils import scheduler_task as scheduler_task_mod
from arknights_mower.utils.operators import Dormitory, Operator, Operators
from arknights_mower.utils.scheduler_task import SchedulerTask, TaskTypes

call_db_mod = importlib.import_module("arknights_mower.agent.tools.call_db")


@contextmanager
def _temporary_record_database(path):
    @contextmanager
    def _conn():
        conn = sqlite3.connect(path)
        try:
            record._ensure_tables(conn)
            yield conn
        finally:
            conn.close()

    previous_tables_created = record._tables_created
    record._tables_created = False
    try:
        with patch.object(record, "_conn", _conn):
            yield
    finally:
        record._tables_created = previous_tables_created


class TestSchedulerEventProjection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.path = self.tmp.name
        self.tmp.close()
        record._tables_created = False

    def tearDown(self):
        os.unlink(self.path)

    def test_task_dispatch_has_one_bounded_text_and_sqlite_fact(self):
        task = SimpleNamespace(
            type=SimpleNamespace(name="RUN_ORDER"),
            time=datetime(2026, 8, 17, 9, 30, 0),
            plan={"room_1_1": [object(), object()]},
            meta_data="room_1_1",
            adjusted=False,
        )

        with (
            _temporary_record_database(self.path),
            patch.object(record.logger, "log") as log,
        ):
            record.emit_log_event(
                "task_dispatch",
                "started",
                level="INFO",
                task=task,
            )

        expected_message = (
            "调度任务开始派发：event=task_dispatch state=started task_type=RUN_ORDER "
            "scheduled_at=2026-08-17T09:30:00 room=room_1_1 "
            "room_count=1 adjusted=false"
        )
        log.assert_called_once_with(20, expected_message, exc_info=False)
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute("SELECT task, level, message FROM log").fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1:], ("INFO", expected_message))
        self.assertEqual(
            json.loads(rows[0][0]),
            {
                "adjusted": False,
                "room": "room_1_1",
                "scheduled_at": "2026-08-17T09:30:00",
                "task_type": "RUN_ORDER",
            },
        )
        self.assertNotIn("object", rows[0][0])
        self.assertNotIn("task_plan", rows[0][0])

    def test_missed_order_is_one_owned_error_fact(self):
        task = SimpleNamespace(
            type=SimpleNamespace(name="RUN_ORDER"),
            time=datetime(2026, 8, 17, 9, 30, 0),
            plan={"room_1_1": ["甲"]},
            meta_data="room_1_1",
            adjusted=False,
        )
        with (
            _temporary_record_database(self.path),
            patch.object(record.logger, "log") as log,
        ):
            record.emit_log_event(
                "missed_order",
                "detected",
                level="ERROR",
                task=task,
                miss_kind="current",
            )

        message = log.call_args.args[1]
        self.assertTrue(
            message.startswith(
                "跑单任务确认漏单：event=missed_order state=detected miss_kind=current "
            )
        )
        self.assertIn("room=room_1_1", message)
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute("SELECT level, message FROM log").fetchall()
        finally:
            conn.close()
        self.assertEqual(rows, [("ERROR", message)])

    def test_retry_recovery_is_one_warning_in_both_projections(self):
        with (
            _temporary_record_database(self.path),
            patch.object(record.logger, "log") as log,
        ):
            record.emit_retry_outcome(
                "scene_recovery",
                "recovered",
                attempt=2,
            )

        message = (
            "场景识别重试后恢复：operation=scene_recovery outcome=recovered attempt=2"
        )
        log.assert_called_once_with(30, message, exc_info=False)
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute("SELECT task, level, message FROM log").fetchall()
        finally:
            conn.close()
        self.assertEqual(rows, [("{}", "WARNING", message)])

    def test_retry_exhaustion_is_one_error_without_exception_text(self):
        with (
            _temporary_record_database(self.path),
            patch.object(record.logger, "log") as log,
        ):
            record.emit_retry_outcome(
                "arrange_room",
                "exhausted",
                attempt=4,
                error=ValueError("operator list including private details"),
            )

        message = (
            "房间排班重试已耗尽：operation=arrange_room outcome=exhausted "
            "attempt=4 error_type=ValueError"
        )
        self.assertNotIn("下一步", message)
        log.assert_called_once_with(40, message, exc_info=True)
        self.assertNotIn("private details", message)
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute("SELECT level, message FROM log").fetchall()
        finally:
            conn.close()
        self.assertEqual(rows, [("ERROR", message)])

    def test_routine_event_cannot_be_shifted_into_sqlite(self):
        with (
            _temporary_record_database(self.path),
            patch.object(record.logger, "log") as log,
        ):
            with record._conn():
                pass
            with self.assertRaises(ValueError):
                record.emit_log_event("poll", "unchanged", level="DEBUG")
            with self.assertRaises(ValueError):
                record.emit_retry_outcome("scene_recovery", "retrying", attempt=1)

        log.assert_not_called()
        conn = sqlite3.connect(self.path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM log").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)

    def test_retry_attempt_uses_frozen_ledger_limit(self):
        with (
            _temporary_record_database(self.path),
            patch.object(record.logger, "log") as log,
        ):
            record.emit_retry_outcome("scene_recovery", "exhausted", attempt=999)

        message = (
            "场景识别重试已耗尽：operation=scene_recovery outcome=exhausted attempt=32"
        )
        log.assert_called_once_with(40, message, exc_info=False)

    def test_unexpected_final_failure_has_one_traceback_owner(self):
        captured = []

        class CaptureHandler(logging.Handler):
            def emit(self, log_record):
                captured.append(log_record)

        handler = CaptureHandler()
        with _temporary_record_database(self.path):
            record.logger.addHandler(handler)
            try:
                try:
                    raise RuntimeError("third-party raw failure")
                except RuntimeError as exc:
                    record.emit_retry_outcome(
                        "reload_room",
                        "exhausted",
                        attempt=1,
                        error=exc,
                    )
            finally:
                record.logger.removeHandler(handler)

        owned = [
            item
            for item in captured
            if "operation=reload_room outcome=exhausted" in item.getMessage()
        ]
        self.assertEqual(len(owned), 1)
        self.assertEqual(
            owned[0].getMessage(),
            "房间重载重试已耗尽：operation=reload_room outcome=exhausted "
            "attempt=1 error_type=RuntimeError",
        )
        self.assertIsNotNone(owned[0].exc_info)
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute("SELECT level, message FROM log").fetchall()
        finally:
            conn.close()
        self.assertEqual(rows, [("ERROR", owned[0].getMessage())])
        self.assertNotIn("third-party raw failure", rows[0][1])

    def test_agent_action_sqlite_success_is_silent(self):
        agent = SimpleNamespace(
            current_room="room_1_1",
            group="group_a",
            is_high=lambda: True,
        )
        owner = SimpleNamespace(operators={"甲": agent})

        def update(*_args, **_kwargs):
            return "updated"

        wrapped = record.save_action_to_sqlite_decorator(update)
        with (
            _temporary_record_database(self.path),
            patch.object(record.logger, "debug") as debug,
        ):
            result = wrapped(owner, "甲", 12.5, "dormitory_1", 0, update_time=True)

        self.assertEqual(result, "updated")
        debug.assert_not_called()
        conn = sqlite3.connect(self.path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM agent_action").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)

    def test_state_cache_sqlite_success_is_silent(self):
        with (
            _temporary_record_database(self.path),
            patch.object(record.logger, "info") as info,
            patch.object(record.logger, "debug") as debug,
        ):
            result = record.save_state_to_db({"tasks": []})

        self.assertTrue(result)
        info.assert_not_called()
        debug.assert_not_called()


class TestMissedOrderStructuredConsumer(unittest.TestCase):
    def test_scheduler_task_parser_accepts_only_the_new_finite_json(self):
        task_json = json.dumps(
            {
                "task_type": "RUN_ORDER",
                "scheduled_at": "2026-08-17T09:30:00",
                "room": "room_1_1",
                "adjusted": False,
            }
        )

        self.assertEqual(
            analyze_mod.extract_scheduler_tasks(task_json, "2026-08-17 09:29:00"),
            [
                {
                    "task_time": "2026-08-17 09:30:00",
                    "planned_at": datetime(2026, 8, 17, 9, 30, 0),
                    "task_type": "RUN_ORDER",
                    "room": "room_1_1",
                    "adjusted": False,
                    "log_local_time": "2026-08-17 09:29:00",
                }
            ],
        )
        self.assertEqual(
            analyze_mod.extract_scheduler_tasks(
                "SchedulerTask(time='2026-08-17 09:30:00',"
                "task_plan={'room_1_1': ['甲']},"
                "task_type=TaskTypes.RUN_ORDER,meta_data='room_1_1')"
            ),
            [],
            "升级后不再为完整 SchedulerTask 文本保留双读 fallback",
        )

    def test_runtime_scan_uses_the_public_time_lookup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "arbitrary-name.log")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "2026-08-17 09:30:00,000 module.py:1 WARNING owner: "
                    "event=operation_retry state=recovered\n"
                )
            start = datetime(2026, 8, 17, 9, 29, 0)
            end = datetime(2026, 8, 17, 9, 31, 0)
            with patch.object(
                analyze_mod, "get_log_by_time", return_value=[path]
            ) as lookup:
                result = analyze_mod.scan_runtime_info_logs(start, end)

        lookup.assert_called_once()
        self.assertEqual(result["files"], ["arbitrary-name.log"])
        self.assertEqual(len(result["entries"]), 1)
        self.assertIn("state=recovered", result["entries"][0]["message"])

    def test_runtime_scan_preserves_public_time_lookup_order(self):
        with tempfile.TemporaryDirectory() as folder:
            early = os.path.join(folder, "z-early.log")
            late = os.path.join(folder, "a-late.log")
            with open(early, "w", encoding="utf-8") as handle:
                handle.write(
                    "2026-08-17 09:30:00,000 module.py:1 INFO owner: event=early\n"
                )
            with open(late, "w", encoding="utf-8") as handle:
                handle.write(
                    "2026-08-17 09:31:00,000 module.py:1 INFO owner: event=late\n"
                )
            with patch.object(
                analyze_mod,
                "get_log_by_time",
                return_value=[early, late],
            ):
                result = analyze_mod.scan_runtime_info_logs(
                    datetime(2026, 8, 17, 9, 29),
                    datetime(2026, 8, 17, 9, 32),
                )

        self.assertEqual(
            [row["message"].split("event=")[-1] for row in result["entries"]],
            ["early", "late"],
        )

    def test_producer_rows_flow_through_listing_resolution_and_analysis(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            path = tmp.name
        try:
            scheduled_at = datetime.now().replace(microsecond=0) - timedelta(minutes=5)
            task = SchedulerTask(
                time=scheduled_at,
                task_plan={"room_1_1": ["Current"]},
                task_type=TaskTypes.RUN_ORDER,
                meta_data="room_1_1",
            )
            with (
                _temporary_record_database(path),
                patch.object(record.logger, "log"),
            ):
                record.emit_log_event(
                    "task_dispatch", "started", level="INFO", task=task
                )
                conn = sqlite3.connect(path)
                try:
                    conn.execute("UPDATE log SET time = time - 1 WHERE level = 'INFO'")
                    conn.commit()
                finally:
                    conn.close()
                record.emit_log_event(
                    "missed_order",
                    "detected",
                    level="ERROR",
                    task=task,
                    miss_kind="current",
                )

            event_rows = analyze_mod.fetch_missed_event_rows(database_path=path)
            listing = analyze_mod.list_missed_orders_payload(database_path=path)
            with patch.object(analyze_mod, "get_log_by_time", return_value=[]):
                analysis = analyze_mod.analyze_missed_order_by_order(
                    order_time=scheduled_at.strftime("%Y-%m-%d %H:%M:%S"),
                    log_event_ts=event_rows[0]["log_utc_time"],
                    database_path=path,
                )

            self.assertEqual(len(event_rows), 1)
            self.assertEqual(listing["count"], 1)
            self.assertEqual(listing["orders"][0]["room"], "room_1_1")
            self.assertEqual(analysis["signal_type"], "current_task_miss")
            self.assertEqual(analysis["run_order_task"]["room"], "room_1_1")
            self.assertNotIn("SchedulerTask(", str(analysis))
        finally:
            os.unlink(path)


class TestDatabaseQueryTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.path = self.tmp.name
        self.tmp.close()
        conn = sqlite3.connect(self.path)
        conn.execute(
            "CREATE TABLE log (time INTEGER, task TEXT, level TEXT, message TEXT)"
        )
        conn.executemany(
            "INSERT INTO log VALUES (?, '{}', 'INFO', ?)",
            [(index, f"event=test state={index}") for index in range(105)],
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.path)

    def test_query_is_read_only_and_returns_at_most_100_rows(self):
        with patch.object(call_db_mod, "get_path", return_value=self.path):
            html = call_db_mod.call_db("SELECT time, level, message FROM log")
            rejected = call_db_mod.call_db("DELETE FROM log")

        self.assertEqual(html.count("<tr>"), 101)
        self.assertIn("仅支持 SELECT", rejected)
        conn = sqlite3.connect(self.path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM log").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 105)


class TestBoundedSchedulerSummaries(unittest.TestCase):
    def test_generated_dorm_task_never_logs_dorm_or_task_repr(self):
        now = datetime(2030, 8, 17, 10, 0, 0)
        dorm = Dormitory(("dormitory_1", 0), name="甲", time=now)
        operator = MagicMock(
            exhaust_require=False,
            current_room="dormitory_1",
            current_index=0,
        )
        operator.is_high.return_value = False
        op_data = MagicMock()
        op_data.operators = {"甲": operator}
        op_data.plan = {"dormitory_1": [object()] * 5}
        op_data.config.free_room = True

        with (
            patch.object(scheduler_task_mod.config.conf, "merge_interval", 0),
            patch.object(scheduler_task_mod.logger, "debug") as debug,
        ):
            result = scheduler_task_mod.generate_plan_by_drom(
                {now: ([dorm], False)}, op_data
            )

        self.assertEqual(len(result), 1)
        debug.assert_called_once_with(
            "宿舍排班任务已生成：task_type=%s scheduled_at=%s room_count=%s",
            TaskTypes.SHIFT_ON.name,
            (now - timedelta(minutes=8)).isoformat(timespec="seconds"),
            1,
        )
        rendered = str(debug.call_args_list)
        self.assertNotIn("Dormitory(", rendered)
        self.assertNotIn("SchedulerTask(", rendered)

    def test_reorder_logs_only_room_and_moved_count(self):
        dorm = Dormitory(("dormitory_1", 0), name="甲")
        op_data = MagicMock()
        op_data.dorm = [dorm]
        op_data.plan = {"dormitory_1": [object()] * 5}
        op_data.config.ope_resting_priority = []
        op_data.operators = {
            "甲": SimpleNamespace(
                operator_type="low",
                resting_priority="low",
                current_room="room_1_1",
                current_index=0,
            )
        }

        with patch.object(scheduler_task_mod.logger, "debug") as debug:
            plan = scheduler_task_mod.try_reorder(op_data, {})

        self.assertEqual(plan["dormitory_1"][0], "甲")
        debug.assert_called_once_with(
            "宿舍排序完成：room=%s moved_operator_count=%s", "dormitory_1", 1
        )
        self.assertNotIn("Dormitory(", str(debug.call_args_list))


class TestBoundedOperatorSummaries(unittest.TestCase):
    def test_operator_add_without_refresh_rooms_is_silent(self):
        operators = Operators.__new__(Operators)
        operators.config = MagicMock()
        operators.config.is_resting_priority.return_value = False
        operators.config.is_exhaust_require.return_value = False
        operators.config.is_rest_in_full.return_value = False
        operators.config.is_workaholic.return_value = False
        operators.config.is_refresh_trading.return_value = [False, []]
        operators.config.is_refresh_drained.return_value = False
        operators.operators = {}
        operators.shadow_copy = {}
        operators.exhaust_agent = set()
        operators.exhaust_group = set()
        operators.groups = {}

        with patch.object(operators_mod.logger, "debug") as debug:
            operators.add(Operator("但书", ""))

        debug.assert_not_called()

    def test_operator_add_bounds_refresh_rooms(self):
        operators = Operators.__new__(Operators)
        operators.config = MagicMock()
        operators.config.is_resting_priority.return_value = False
        operators.config.is_exhaust_require.return_value = False
        operators.config.is_rest_in_full.return_value = False
        operators.config.is_workaholic.return_value = False
        operators.config.is_refresh_trading.return_value = [
            True,
            [f"room_{index}" for index in range(12)],
        ]
        operators.config.is_refresh_drained.return_value = False
        operators.operators = {}
        operators.shadow_copy = {}
        operators.exhaust_agent = set()
        operators.exhaust_group = set()
        operators.groups = {}

        with patch.object(operators_mod.logger, "debug") as debug:
            operators.add(Operator("但书", ""))

        debug.assert_called_once_with(
            "干员刷新房间已记录：operator=%s refresh_rooms=%s",
            "但书",
            ",".join(f"room_{index}" for index in range(8)),
        )

    def test_operator_add_bounds_each_identifier(self):
        operators = Operators.__new__(Operators)
        operators.config = MagicMock()
        operators.config.is_resting_priority.return_value = False
        operators.config.is_exhaust_require.return_value = False
        operators.config.is_rest_in_full.return_value = False
        operators.config.is_workaholic.return_value = False
        operators.config.is_refresh_trading.return_value = [
            True,
            [("r" * 40) + "\nsecret" for _ in range(10)],
        ]
        operators.config.is_refresh_drained.return_value = False
        operators.operators = {}
        operators.shadow_copy = {}
        operators.exhaust_agent = set()
        operators.exhaust_group = set()
        operators.groups = {}
        long_name = "o" * 80

        with (
            patch.object(operators_mod, "agent_list", [long_name]),
            patch.object(operators_mod.logger, "debug") as debug,
        ):
            operators.add(Operator(long_name, ""))

        args = debug.call_args.args
        self.assertEqual(args[1], "o" * 64)
        rooms = args[2].split(",")
        self.assertEqual(len(rooms), 8)
        self.assertTrue(all(room == "r" * 32 for room in rooms))

    def test_current_room_callback_logs_only_bounded_fields(self):
        callback = MagicMock()
        previous_callback = Operators.current_room_changed_callback
        Operators.current_room_changed_callback = None
        try:
            operator = Operator("但书", "", refresh_order_room=[True, ["room_1_1"]])
            Operators.current_room_changed_callback = callback
            with patch.object(operators_mod.logger, "debug") as debug:
                operator.current_room = "room_1_2"
        finally:
            Operators.current_room_changed_callback = previous_callback

        callback.assert_called_once_with(operator)
        debug.assert_called_once_with(
            "干员当前房间已更新：operator=%s room=%s "
            "refresh_room_count=%s refresh_mood=%s",
            "但书",
            "room_1_2",
            1,
            False,
        )


if __name__ == "__main__":
    unittest.main()
