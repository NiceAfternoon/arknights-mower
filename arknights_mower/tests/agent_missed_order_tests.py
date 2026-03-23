import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

with patch.dict("sys.modules", {"colorlog": MagicMock(), "requests": MagicMock()}):
    from arknights_mower.agent.tools.analyze_missed_order import (
        detect_log_gap,
        extract_run_order_candidates,
        extract_scheduler_tasks,
        select_primary_run_order,
    )


class TestMissedOrderTool(unittest.TestCase):
    def test_extract_scheduler_tasks(self):
        text = (
            "SchedulerTask(time='2026-02-24 09:10:10.338501',task_plan={'room_1_1': "
            "['Current', '但书']},task_type=TaskTypes.RUN_ORDER,meta_data='room_1_1',"
            "adjusted=False)"
        )
        result = extract_scheduler_tasks(text, "2026-02-23 17:10:12")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["task_type"], "RUN_ORDER")
        self.assertEqual(result[0]["room"], "room_1_1")
        self.assertFalse(result[0]["adjusted"])

    def test_extract_run_order_candidates(self):
        log_rows = [
            {
                "local_time": "2026-02-23 17:10:12",
                "level": "INFO",
                "task": (
                    "SchedulerTask(time='2026-02-24 09:10:10.338501',task_plan={'room_1_1': "
                    "['Current', '但书']},task_type=TaskTypes.RUN_ORDER,meta_data='room_1_1',"
                    "adjusted=False)"
                ),
                "message": "",
            }
        ]
        result = extract_run_order_candidates(log_rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["room"], "room_1_1")
        self.assertEqual(result[0]["planned_time"], "2026-02-24 09:10:10")

    def test_select_primary_run_order(self):
        candidates = [
            {
                "planned_time": "2026-02-24 08:18:43",
                "planned_at": datetime.strptime(
                    "2026-02-24 08:18:43", "%Y-%m-%d %H:%M:%S"
                ),
                "room": "room_3_1",
                "log_time": "2026-02-23 16:18:45",
            },
            {
                "planned_time": "2026-02-24 09:10:10",
                "planned_at": datetime.strptime(
                    "2026-02-24 09:10:10", "%Y-%m-%d %H:%M:%S"
                ),
                "room": "room_1_1",
                "log_time": "2026-02-23 17:10:12",
            },
        ]
        target_time = datetime.strptime("2026-02-24 11:06:16", "%Y-%m-%d %H:%M:%S")
        result = select_primary_run_order(target_time, candidates)
        self.assertEqual(result["room"], "room_1_1")

    def test_detect_log_gap(self):
        log_rows = [
            {"local_time": "2026-02-24 09:00:00"},
            {"local_time": "2026-02-24 09:05:00"},
            {"local_time": "2026-02-24 10:00:00"},
        ]
        result = detect_log_gap(
            log_rows,
            datetime.strptime("2026-02-24 09:00:00", "%Y-%m-%d %H:%M:%S"),
            datetime.strptime("2026-02-24 10:05:00", "%Y-%m-%d %H:%M:%S"),
        )
        self.assertTrue(result["has_gap"])


if __name__ == "__main__":
    unittest.main()
