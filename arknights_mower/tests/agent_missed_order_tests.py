import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

with patch.dict("sys.modules", {"colorlog": MagicMock(), "requests": MagicMock()}):
    from arknights_mower.agent.missed_order import (
        format_missed_order_list,
        format_missed_order_task_records,
        summarize_missed_order_result,
    )
    from arknights_mower.agent.tools.analyze_missed_order import (
        analyze_missed_order,
        analyze_missed_order_by_order,
        analyze_missed_order_by_time,
    )


class TestMissedOrderTool(unittest.TestCase):
    @staticmethod
    def _ts(local_time: str) -> int:
        return int(datetime.strptime(local_time, "%Y-%m-%d %H:%M:%S").timestamp())

    @patch("arknights_mower.agent.tools.analyze_missed_order.scan_runtime_info_logs")
    @patch("arknights_mower.agent.tools.analyze_missed_order.fetch_logs_by_utc_window")
    @patch("arknights_mower.agent.tools.analyze_missed_order.fetch_missed_event_rows")
    def test_analyze_by_order_current_task_miss(
        self, mock_fetch_events, mock_fetch_logs, mock_runtime
    ):
        mock_runtime.return_value = {
            "files": ["runtime.log.2026-02-18_22"],
            "entries": [
                {
                    "time": "2026-02-18 22:11:19",
                    "file": "runtime.log.2026-02-18_22",
                    "message": "2026-02-18 22:11:19 INFO 检测到漏单",
                }
            ],
        }
        mock_fetch_events.return_value = [
            {
                "log_utc_time": self._ts("2026-02-18 22:11:06"),
                "log_local_time": "2026-02-18 22:11:06",
                "level": "ERROR",
                "task": "{}",
                "message": "检测到漏单！",
            }
        ]
        mock_fetch_logs.side_effect = [
            [
                {
                    "log_utc_time": self._ts("2026-02-18 21:57:06"),
                    "log_local_time": "2026-02-18 21:57:06",
                    "level": "INFO",
                    "task": (
                        "SchedulerTask(time='2026-02-18 22:06:22',task_plan={'room_3_1': "
                        "['Current']},task_type=TaskTypes.RUN_ORDER,meta_data='room_3_1',"
                        "adjusted=False)"
                    ),
                    "message": "",
                },
                {
                    "log_utc_time": self._ts("2026-02-18 22:11:06"),
                    "log_local_time": "2026-02-18 22:11:06",
                    "level": "ERROR",
                    "task": "{}",
                    "message": "检测到漏单！",
                },
            ]
        ]
        result = analyze_missed_order_by_order(
            order_time="2026-02-18 22:06:22",
            signal_type="current_task_miss",
            log_event_time="2026-02-18 22:11:06",
            log_event_ts=self._ts("2026-02-18 22:11:06"),
            room="room_3_1",
        )
        self.assertEqual(result["signal_type"], "current_task_miss")
        self.assertEqual(result["target_task_time"], "2026-02-18 22:06:22")
        self.assertEqual(result["current_task_time"], "2026-02-18 22:06:22")
        self.assertEqual(result["detected_time"], "2026-02-18 22:11:19")
        self.assertEqual(result["room"], "room_3_1")

    @patch("arknights_mower.agent.tools.analyze_missed_order.scan_runtime_info_logs")
    @patch("arknights_mower.agent.tools.analyze_missed_order.fetch_logs_by_utc_window")
    @patch("arknights_mower.agent.tools.analyze_missed_order.fetch_missed_event_rows")
    def test_analyze_by_order_previous_order_miss(
        self, mock_fetch_events, mock_fetch_logs, mock_runtime
    ):
        mock_runtime.return_value = {"files": [], "entries": []}
        mock_fetch_events.return_value = [
            {
                "log_utc_time": self._ts("2026-02-18 23:40:00"),
                "log_local_time": "2026-02-18 23:40:00",
                "level": "ERROR",
                "task": "{}",
                "message": "检测到上一个订单漏单！",
            }
        ]
        mock_fetch_logs.side_effect = [
            [
                {
                    "log_utc_time": self._ts("2026-02-18 20:00:00"),
                    "log_local_time": "2026-02-18 20:00:00",
                    "level": "INFO",
                    "task": (
                        "SchedulerTask(time='2026-02-18 20:00:00',task_plan={'room_3_1': "
                        "['Current']},task_type=TaskTypes.RUN_ORDER,meta_data='room_3_1',"
                        "adjusted=False)"
                    ),
                    "message": "",
                },
                {
                    "log_utc_time": self._ts("2026-02-18 22:06:22"),
                    "log_local_time": "2026-02-18 22:06:22",
                    "level": "INFO",
                    "task": (
                        "SchedulerTask(time='2026-02-18 22:06:22',task_plan={'room_3_1': "
                        "['Current']},task_type=TaskTypes.RUN_ORDER,meta_data='room_3_1',"
                        "adjusted=False)"
                    ),
                    "message": "",
                },
                {
                    "log_utc_time": self._ts("2026-02-18 23:40:00"),
                    "log_local_time": "2026-02-18 23:40:00",
                    "level": "ERROR",
                    "task": "{}",
                    "message": "检测到上一个订单漏单！",
                },
            ]
        ]
        result = analyze_missed_order_by_order(
            order_time="2026-02-18 20:00:00",
            signal_type="previous_order_miss",
            log_event_time="2026-02-18 23:40:00",
            log_event_ts=self._ts("2026-02-18 23:40:00"),
            room="room_3_1",
        )
        self.assertEqual(result["signal_type"], "previous_order_miss")
        self.assertEqual(result["target_task_time"], "2026-02-18 20:00:00")
        self.assertEqual(result["current_task_time"], "2026-02-18 22:06:22")
        self.assertEqual(result["previous_task_time"], "2026-02-18 20:00:00")

    @patch("arknights_mower.agent.tools.analyze_missed_order.scan_runtime_info_logs")
    @patch("arknights_mower.agent.tools.analyze_missed_order.fetch_missed_event_rows")
    @patch("arknights_mower.agent.tools.analyze_missed_order.fetch_logs_by_utc_window")
    def test_analyze_by_time_matches_by_task_time(
        self, mock_fetch_logs, mock_fetch_events, mock_runtime
    ):
        mock_runtime.return_value = {"files": [], "entries": []}
        mock_fetch_events.return_value = [
            {
                "log_utc_time": self._ts("2026-02-18 22:11:06"),
                "log_local_time": "2026-02-18 22:11:06",
                "level": "ERROR",
                "task": "{}",
                "message": "检测到漏单！",
            }
        ]
        mock_fetch_logs.return_value = [
            {
                "log_utc_time": self._ts("2026-02-18 21:57:06"),
                "log_local_time": "2026-02-18 21:57:06",
                "level": "INFO",
                "task": (
                    "SchedulerTask(time='2026-02-18 22:06:22',task_plan={'room_3_1': "
                    "['Current']},task_type=TaskTypes.RUN_ORDER,meta_data='room_3_1',"
                    "adjusted=False)"
                ),
                "message": "",
            },
            {
                "log_utc_time": self._ts("2026-02-18 22:11:06"),
                "log_local_time": "2026-02-18 22:11:06",
                "level": "ERROR",
                "task": "{}",
                "message": "检测到漏单！",
            },
        ]
        result = analyze_missed_order_by_time("2026-02-18 22:06:22")
        self.assertEqual(result["target_task_time"], "2026-02-18 22:06:22")
        self.assertEqual(result["room"], "room_3_1")

    @patch("arknights_mower.agent.tools.analyze_missed_order.fetch_missed_event_rows")
    def test_list_orders_mode(self, mock_fetch_events):
        mock_fetch_events.return_value = [
            {
                "log_utc_time": self._ts("2026-02-18 22:11:06"),
                "log_local_time": "2026-02-18 22:11:06",
                "level": "ERROR",
                "task": "{}",
                "message": "检测到漏单！",
            }
        ]
        with patch(
            "arknights_mower.agent.tools.analyze_missed_order.resolve_event_context"
        ) as mock_context:
            mock_context.return_value = {
                "signal_type": "current_task_miss",
                "target_task": {"task_time": "2026-02-18 22:06:22"},
                "current_task": {"task_time": "2026-02-18 22:06:22"},
                "previous_task": None,
                "room": "room_3_1",
            }
            payload = json.loads(analyze_missed_order(mode="list_orders"))
        self.assertEqual(payload["mode"], "list_orders")
        self.assertTrue(payload["has_orders"])
        self.assertEqual(payload["orders"][0]["task_time"], "2026-02-18 22:06:22")

    def test_format_report_uses_new_fields(self):
        result = {
            "signal_type": "current_task_miss",
            "room": "room_3_1",
            "target_task_time": "2026-02-18 22:06:22",
            "current_task_time": "2026-02-18 22:06:22",
            "previous_task_time": None,
            "detected_time": "2026-02-18 22:11:19",
            "db_query_window": {"start": 1, "end": 2},
            "runtime_window": {
                "start": "2026-02-18 22:01:22",
                "end": "2026-02-18 22:11:19",
            },
            "timeline_logs": [],
            "runtime_info_logs": [],
            "candidate_reasons": [
                {
                    "type": "execution_failed",
                    "confidence_hint": "medium",
                    "supported_evidence": ["数据库时间线中存在 ERROR 日志"],
                }
            ],
        }
        text = format_missed_order_task_records(result)
        self.assertIn("目标任务时间：2026-02-18 22:06:22", text)
        self.assertIn("检测到漏单时间：2026-02-18 22:11:19", text)
        self.assertNotIn("A/B/C", text)

    def test_list_format_uses_new_fields(self):
        text = format_missed_order_list(
            [
                {
                    "index": 1,
                    "log_local_time": "2026-02-18 22:11:06",
                    "level": "ERROR",
                    "message": "检测到漏单！",
                    "task_time": "2026-02-18 22:06:22",
                    "room": "room_3_1",
                }
            ]
        )
        self.assertIn(
            "事件=2026-02-18 22:11:06 | 任务=2026-02-18 22:06:22 | 房间=room_3_1", text
        )

    def test_summary_fallback_uses_new_fields(self):
        text = summarize_missed_order_result(
            {
                "target_task_time": "2026-02-18 22:06:22",
                "current_task_time": "2026-02-18 22:06:22",
                "previous_task_time": None,
                "detected_time": "2026-02-18 22:11:19",
                "room": "room_3_1",
                "candidate_reasons": [{"type": "execution_failed"}],
            },
            llm=None,
        )
        self.assertIn("目标任务时间：2026-02-18 22:06:22", text)
        self.assertNotIn("A/B/C", text)


if __name__ == "__main__":
    unittest.main()
