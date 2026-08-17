"""#121 项目自有日志中文正文与固定审计范围合同。"""

import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
AUDIT_PATH = Path(__file__).with_name("fixtures") / "log_message_audit.json"
VOLUME_PATH = Path(__file__).with_name("fixtures") / "log_chinese_volume_fixture.json"
FIELD_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)(?==)")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _string_constants(node: ast.AST) -> list[str]:
    return [
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    ]


def _field_names(node: ast.AST) -> list[str]:
    fields = []
    for field in FIELD_RE.findall(" ".join(_string_constants(node))):
        if field not in fields:
            fields.append(field)
    return fields


def _function_nodes(tree: ast.AST, name: str) -> list[ast.AST]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]


class ProjectLogChineseAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        cls.trees = {}

    @classmethod
    def _tree(cls, relative_path: str) -> ast.AST:
        if relative_path not in cls.trees:
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            cls.trees[relative_path] = ast.parse(source)
        return cls.trees[relative_path]

    def test_frozen_scope_and_before_count_are_pinned(self):
        scope = self.audit["scope"]
        self.assertEqual(scope["frozen_ledger_rows"], 749)
        self.assertEqual(scope["scope_required"], 278)
        self.assertEqual(scope["scope_consistency"], 471)
        self.assertEqual(scope["project_english_before"], 146)
        self.assertEqual(
            sum(item["count"] for item in self.audit["direct_producer_groups"]),
            scope["direct_project_english_before"],
        )
        self.assertEqual(
            len(self.audit["dynamic_producers"]),
            scope["dynamic_project_english_before"],
        )

    def test_pinned_project_owned_producers_have_chinese_bodies(self):
        violations = []
        for group in self.audit["direct_producer_groups"]:
            calls = []
            for function_node in _function_nodes(
                self._tree(group["path"]), group["function"]
            ):
                for node in ast.walk(function_node):
                    if not isinstance(node, ast.Call) or not node.args:
                        continue
                    func = node.func
                    if not (
                        isinstance(func, ast.Attribute)
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "logger"
                        and func.attr == group["method"]
                    ):
                        continue
                    if _field_names(node.args[0]) == group["field_names"]:
                        calls.append(node)
            self.assertEqual(
                len(calls),
                group["count"],
                f"审计生产者漂移：{group}",
            )
            for node in calls:
                body = " ".join(_string_constants(node.args[0]))
                if not CJK_RE.search(body):
                    violations.append(
                        f"{group['path']}:{node.lineno} {group['function']} {body}"
                    )

        for producer in self.audit["dynamic_producers"]:
            functions = _function_nodes(
                self._tree(producer["path"]), producer["function"]
            )
            self.assertEqual(len(functions), 1, f"动态生产者漂移：{producer}")
            source_text = " ".join(_string_constants(functions[0]))
            for required in producer["required_chinese"]:
                if required not in source_text:
                    violations.append(
                        f"{producer['path']} {producer['function']} 缺少 {required}"
                    )

        self.assertEqual(violations, [], "\n" + "\n".join(violations))


class DeterministicVolumeContractTests(unittest.TestCase):
    def test_translation_keeps_record_count_and_pins_utf8_crlf_bytes(self):
        fixture = json.loads(VOLUME_PATH.read_text(encoding="utf-8"))

        def materialize(key: str) -> bytes:
            lines = [
                fixture["envelope"].format(level=item["level"], message=item[key])
                for item in fixture["records"]
            ]
            return ("\r\n".join(lines) + "\r\n").encode("utf-8")

        before = materialize("before")
        after = materialize("after")

        self.assertEqual(fixture["encoding"], "UTF-8")
        self.assertEqual(fixture["line_ending"], "CRLF")
        self.assertEqual(len(fixture["records"]), 7)
        self.assertEqual(before.count(b"\r\n"), 7)
        self.assertEqual(after.count(b"\r\n"), 7)
        self.assertEqual(len(before), 988)
        self.assertEqual(len(after), 1228)


if __name__ == "__main__":
    unittest.main()
