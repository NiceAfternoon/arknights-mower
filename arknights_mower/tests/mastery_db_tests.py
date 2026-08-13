import os
import sqlite3
import tempfile
import unittest

from arknights_mower.utils.mastery_db import (
    delete_plan,
    get_active_plan,
    get_all_plans,
    get_failed_plans,
    get_next_idle_plan,
    get_plan_by_id,
    get_route,
    insert_plan,
    is_operator_busy,
    save_route,
    should_notify,
    update_plan_priority,
    update_plan_status,
)


class TestMasteryDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_insert_and_get(self):
        pid = insert_plan("char_001", 0, 1, skill_name="技能1", path=self.db_path)
        self.assertGreater(pid, 0)
        plan = get_plan_by_id(pid, path=self.db_path)
        self.assertEqual(plan["char_id"], "char_001")
        self.assertEqual(plan["skill_index"], 0)
        self.assertEqual(plan["target_level"], 1)
        self.assertEqual(plan["status"], "idle")
        self.assertEqual(plan["swap_frozen"], 0)

    def test_get_all_plans_excludes_completed(self):
        p1 = insert_plan("char_001", 0, 1, path=self.db_path)
        p2 = insert_plan("char_002", 1, 2, path=self.db_path)
        update_plan_status(p1, "completed", path=self.db_path)
        plans = get_all_plans(path=self.db_path)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["id"], p2)

    def test_priority_ordering(self):
        insert_plan("char_a", 0, 1, priority=10, path=self.db_path)
        insert_plan("char_b", 0, 1, priority=1, path=self.db_path)
        insert_plan("char_c", 0, 1, priority=5, path=self.db_path)
        plans = get_all_plans(path=self.db_path)
        priorities = [p["priority"] for p in plans]
        self.assertEqual(priorities, [1, 5, 10])

    def test_get_active_plan(self):
        p1 = insert_plan("char_001", 0, 1, path=self.db_path)
        self.assertIsNone(get_active_plan(path=self.db_path))
        update_plan_status(p1, "training", path=self.db_path)
        active = get_active_plan(path=self.db_path)
        self.assertEqual(active["id"], p1)

    def test_get_next_idle_plan(self):
        insert_plan("char_a", 0, 1, priority=5, path=self.db_path)
        insert_plan("char_b", 0, 1, priority=1, path=self.db_path)
        nxt = get_next_idle_plan(path=self.db_path)
        self.assertEqual(nxt["char_id"], "char_b")

    def test_get_failed_plans(self):
        # #69：failed 计划带失败原因单独可查（前端展示用），active 计划不混入
        p1 = insert_plan("char_001", 0, 1, path=self.db_path)
        p2 = insert_plan("char_002", 1, 2, path=self.db_path)
        update_plan_status(p2, "failed", failed_reason="材料不足", path=self.db_path)
        update_plan_status(p1, "training", path=self.db_path)
        failed = get_failed_plans(path=self.db_path)
        self.assertEqual([f["id"] for f in failed], [p2])
        self.assertEqual(failed[0]["failed_reason"], "材料不足")

    def test_update_status(self):
        pid = insert_plan("char_001", 0, 1, path=self.db_path)
        self.assertTrue(update_plan_status(pid, "arranging", path=self.db_path))
        plan = get_plan_by_id(pid, path=self.db_path)
        self.assertEqual(plan["status"], "arranging")

    def test_update_status_invalid(self):
        pid = insert_plan("char_001", 0, 1, path=self.db_path)
        self.assertFalse(update_plan_status(pid, "bogus", path=self.db_path))

    def test_update_status_with_extras(self):
        pid = insert_plan("char_001", 0, 1, path=self.db_path)
        update_plan_status(
            pid,
            "training",
            expires_at="2026-01-01 12:00:00",
            swap_frozen=1,
            path=self.db_path,
        )
        plan = get_plan_by_id(pid, path=self.db_path)
        self.assertEqual(plan["expires_at"], "2026-01-01 12:00:00")
        self.assertEqual(plan["swap_frozen"], 1)

    def test_update_priority(self):
        pid = insert_plan("char_001", 0, 1, priority=5, path=self.db_path)
        update_plan_priority(pid, 1, path=self.db_path)
        plan = get_plan_by_id(pid, path=self.db_path)
        self.assertEqual(plan["priority"], 1)

    def test_delete_plan(self):
        pid = insert_plan("char_001", 0, 1, path=self.db_path)
        self.assertTrue(delete_plan(pid, path=self.db_path))
        self.assertIsNone(get_plan_by_id(pid, path=self.db_path))

    def test_is_operator_busy(self):
        pid = insert_plan("char_001", 0, 1, path=self.db_path)
        self.assertFalse(is_operator_busy("char_001", path=self.db_path))
        update_plan_status(pid, "training", path=self.db_path)
        self.assertTrue(is_operator_busy("char_001", path=self.db_path))
        self.assertFalse(is_operator_busy("char_002", path=self.db_path))

    def test_is_operator_busy_waits_collect(self):
        # #59：waiting_collect（练完没收）也算 busy，不能把训练中干员当空闲挪走
        pid = insert_plan("char_001", 0, 1, path=self.db_path)
        update_plan_status(pid, "waiting_collect", path=self.db_path)
        self.assertTrue(is_operator_busy("char_001", path=self.db_path))

    def test_is_operator_busy_resolves_null_char_name(self):
        # #59：存量计划 char_name 为 NULL 时按名匹配也能命中（回退查表）
        pid = insert_plan("char_103_angel", 0, 1, char_name=None, path=self.db_path)
        update_plan_status(pid, "training", path=self.db_path)
        self.assertTrue(is_operator_busy("能天使", path=self.db_path))

    def test_insert_plan_canonicalizes_skill_name(self):
        # #63：计划 skill_name 存规范格式 `{序数}技能·真名`（真名并入 skill_data.json）
        pid = insert_plan("char_103_angel", 1, 3, path=self.db_path)
        plan = get_plan_by_id(pid, path=self.db_path)
        self.assertEqual(plan["skill_name"], "二技能·扫射模式")

    def test_lazy_fill_legacy_plan(self):
        # #63：存量占位 skill_name（技能N）/ NULL char_name 在读取时懒填充
        import sqlite3

        get_all_plans(path=self.db_path)  # 触发建表
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "INSERT INTO mastery_plan "
                "(char_id, char_name, skill_index, skill_name, target_level, priority) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("char_103_angel", None, 0, "技能1", 2, 0),
            )
            pid = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        plan = get_plan_by_id(pid, path=self.db_path)
        self.assertEqual(plan["skill_name"], "一技能·冲锋模式")
        self.assertEqual(plan["char_name"], "能天使")

    def test_should_notify_once(self):
        # #61：通知仅三类各一次（同 dedup_key 只发一次）
        self.assertTrue(
            should_notify("blocked", "2026-08-01 14:00:00", path=self.db_path)
        )
        self.assertFalse(
            should_notify("blocked", "2026-08-01 14:00:00", path=self.db_path)
        )
        self.assertTrue(
            should_notify("blocked", "2026-08-01 15:00:00", path=self.db_path)
        )
        self.assertTrue(should_notify("fake_reset", "5", path=self.db_path))
        # m3_collect 类型：同 dedup_key 首次 True、再次 False；换 key 重新 True
        self.assertTrue(should_notify("m3_collect", "7", path=self.db_path))
        self.assertFalse(should_notify("m3_collect", "7", path=self.db_path))
        self.assertTrue(should_notify("m3_collect", "8", path=self.db_path))

    def test_route_crud(self):
        save_route("近卫", '{"level_1": {"operator": "赤冬"}}', path=self.db_path)
        route = get_route("近卫", path=self.db_path)
        self.assertIsNotNone(route)
        self.assertIn("赤冬", route["supports"])

    def test_route_fallback_to_default(self):
        save_route(
            "近卫",
            '{"level_1": {"operator": "default"}}',
            is_default=1,
            path=self.db_path,
        )
        route = get_route("近卫", path=self.db_path)
        self.assertIn("default", route["supports"])
        save_route(
            "近卫",
            '{"level_1": {"operator": "custom"}}',
            is_default=0,
            path=self.db_path,
        )
        route = get_route("近卫", path=self.db_path)
        self.assertIn("custom", route["supports"])

    def test_route_settings_round_trip(self):
        save_route(
            "近卫",
            "[]",
            optimal=True,
            half_off=False,
            path=self.db_path,
        )

        route = get_route("近卫", path=self.db_path)

        self.assertEqual(route["supports"], "[]")
        self.assertEqual(route["optimal"], 1)
        self.assertEqual(route["half_off"], 0)

    def test_route_schema_migrates_existing_database(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "CREATE TABLE mastery_route ("
                "profession TEXT NOT NULL,"
                "supports TEXT NOT NULL DEFAULT '{}',"
                "is_default INTEGER DEFAULT 0,"
                "created_at TEXT DEFAULT (datetime('now','localtime')) ,"
                "UNIQUE(profession, is_default)"
                ")"
            )
            conn.execute(
                "INSERT INTO mastery_route (profession, supports, is_default) VALUES (?, ?, ?)",
                ("近卫", "[]", 0),
            )
            conn.commit()
        finally:
            conn.close()

        route = get_route("近卫", path=self.db_path)

        self.assertEqual(route["optimal"], 0)
        self.assertEqual(route["half_off"], 1)
        conn = sqlite3.connect(self.db_path)
        try:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(mastery_route)")
            }
        finally:
            conn.close()
        self.assertIn("optimal", columns)
        self.assertIn("half_off", columns)


if __name__ == "__main__":
    unittest.main()
