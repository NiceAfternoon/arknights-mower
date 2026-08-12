import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from arknights_mower.log_baseline import (
    analyze_window,
    capture_window,
    freeze_ledger,
    main,
)


def _pareto_row(
    source: str,
    function: str,
    count: int,
    byte_count: int,
    message_shape: str | None = None,
    level: str = "DEBUG",
) -> dict:
    return {
        "source": source,
        "function": function,
        "level": level,
        "message_shape": message_shape or function,
        "count": count,
        "actual_file_bytes": byte_count,
    }


def _ledger_report(
    window_number: int,
    pareto: list[dict],
    *,
    started_at: str | None = None,
    ended_at: str | None = None,
    total_records: int = 100,
    total_bytes: int = 1000,
) -> dict:
    start_hour = 10 + (window_number - 1) * 3
    return {
        "window": {
            "window_id": f"before-{window_number}",
            "phase": "before",
            "started_at": started_at or f"2026-08-11T{start_hour:02}:00:00+08:00",
            "ended_at": ended_at or f"2026-08-11T{start_hour + 2:02}:00:00+08:00",
            "environment": {"same": True},
        },
        "validity": {"valid": True, "reasons": []},
        "totals": {
            "logical_records": total_records,
            "actual_file_bytes": total_bytes,
        },
        "pareto": pareto,
    }


def _ledger_row(
    source: str,
    function: str,
    *,
    message_shape: str | None = None,
    target_message_shape: str = "<silent>",
    category: str = "repeated_polling",
    decision: str = "include",
    change: str = "silent",
    bounded_fields: list[dict] | None = None,
    selection_basis: str = "scope_required",
    level: str = "DEBUG",
) -> dict:
    return {
        "source": source,
        "function": function,
        "level": level,
        "message_shape": message_shape or function,
        "target_message_shape": target_message_shape,
        "category": category,
        "consumers": ["text"],
        "decision": decision,
        "reason": "candidate",
        "change": change,
        "bounded_fields": bounded_fields or [],
        "test": "contract",
        "selection_basis": selection_basis,
    }


class TestLogBaseline(unittest.TestCase):
    def test_capture_metrics_include_descendant_processes(self):
        child_script = "\n".join(
            [
                "import time",
                "payload = bytearray(64 * 1024 * 1024)",
                "started = time.perf_counter()",
                "while time.perf_counter() - started < 0.35:",
                "    sum(value * value for value in range(2000))",
                "time.sleep(0.15)",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live_log_dir = root / "live-log"
            live_log_dir.mkdir()
            database_path = root / "data.db"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    "CREATE TABLE log (time INTEGER, task TEXT, level TEXT, message TEXT)"
                )
                connection.commit()
            finally:
                connection.close()
            producer = root / "producer.py"
            producer.write_text(
                "\n".join(
                    [
                        "import subprocess, sys",
                        f"subprocess.run([sys.executable, '-c', {child_script!r}], check=True)",
                    ]
                ),
                encoding="utf-8",
            )

            report = capture_window(
                command=[sys.executable, str(producer)],
                live_log_dir=live_log_dir,
                database_path=database_path,
                output_dir=root / "capture",
                manifest={"window_id": "process-tree-probe", "phase": "before"},
                poll_interval=0.01,
            )

        self.assertGreater(report["metrics"]["cpu_seconds"], 0.1)
        self.assertGreater(report["metrics"]["peak_rss_bytes"], 48 * 1024 * 1024)

    def test_coverage_threshold_cannot_be_lowered(self):
        with self.assertRaises(TypeError):
            freeze_ledger([], [], threshold=0.1)

    def test_freeze_ledger_requires_three_unique_window_ids(self):
        report = _ledger_report(1, [_pareto_row("core.py:1", "core", 100, 1000)])
        declaration = [_ledger_row("core.py:1", "core")]

        ledger = freeze_ledger([report, report, report], declaration)

        self.assertIn(
            "before windows must have unique window IDs",
            ledger["validity"]["reasons"],
        )

    def test_freeze_ledger_requires_nonoverlapping_aware_windows(self):
        intervals = (
            (
                "2026-08-11T10:00:00+08:00",
                "2026-08-11T12:00:00+08:00",
            ),
            (
                "2026-08-11T11:00:00+08:00",
                "2026-08-11T13:00:00+08:00",
            ),
            (
                "2026-08-11T14:00:00+08:00",
                "2026-08-11T16:00:00+08:00",
            ),
        )
        reports = [
            _ledger_report(
                index,
                [_pareto_row("core.py:1", "core", 100, 1000)],
                started_at=started_at,
                ended_at=ended_at,
            )
            for index, (started_at, ended_at) in enumerate(intervals, start=1)
        ]
        declaration = [_ledger_row("core.py:1", "core")]

        ledger = freeze_ledger(reports, declaration)

        self.assertIn("before windows must not overlap", ledger["validity"]["reasons"])

    def test_freeze_ledger_rejects_unbounded_target_message_shape(self):
        reports = [
            _ledger_report(
                index,
                [_pareto_row("core.py:1", "core", 100, 1000, "state=<object>")],
            )
            for index in range(1, 4)
        ]
        declaration = [
            _ledger_row(
                "core.py:1",
                "core",
                message_shape="state=<object>",
                target_message_shape="state=<object>",
                category="object_dump",
                change="progress_summary",
                bounded_fields=[
                    {
                        "name": "state",
                        "kind": "enum",
                        "values": ["idle", "running"],
                    }
                ],
            )
        ]

        ledger = freeze_ledger(reports, declaration)

        self.assertIn(
            "ledger row 1 target_message_shape must not preserve object dumps or truncation",
            ledger["validity"]["reasons"],
        )

    def test_freeze_ledger_requires_explicit_limits_for_target_fields(self):
        reports = [
            _ledger_report(
                index,
                [_pareto_row("core.py:1", "core", 100, 1000, "payload")],
            )
            for index in range(1, 4)
        ]
        declaration = [
            _ledger_row(
                "core.py:1",
                "core",
                message_shape="payload",
                target_message_shape="payload={payload}",
                change="progress_summary",
                bounded_fields=["payload"],  # type: ignore[list-item]
            )
        ]

        ledger = freeze_ledger(reports, declaration)

        self.assertIn(
            "ledger row 1 bounded_fields must define explicit finite limits",
            ledger["validity"]["reasons"],
        )

    def test_freeze_ledger_rejects_dump_then_truncate_change(self):
        reports = [
            _ledger_report(
                index,
                [_pareto_row("core.py:1", "core", 100, 1000, "payload")],
            )
            for index in range(1, 4)
        ]
        declaration = [
            _ledger_row(
                "core.py:1",
                "core",
                message_shape="payload",
                target_message_shape="payload={payload}",
                change="dump payload then truncate",
                bounded_fields=[
                    {"name": "payload", "kind": "string", "max_length": 64}
                ],
            )
        ]

        ledger = freeze_ledger(reports, declaration)

        self.assertIn(
            "ledger row 1 change must not dump objects or truncate output",
            ledger["validity"]["reasons"],
        )

    def test_window_rejects_more_than_five_minutes_of_overrun(self):
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            manifest = {
                "started_at": "2026-08-11T10:00:00+08:00",
                "ended_at": "2026-08-11T12:05:01+08:00",
            }

            report = analyze_window(log_dir, manifest=manifest)

        self.assertIn(
            "window duration must not exceed 7500 seconds",
            report["validity"]["reasons"],
        )

    def test_sqlite_window_includes_rows_from_fractional_end_second(self):
        manifest = {
            "started_at": "2026-08-11T10:00:00.100000+08:00",
            "ended_at": "2026-08-11T10:00:00.900000+08:00",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_dir = root / "log"
            log_dir.mkdir()
            database_path = root / "data.db"
            event_second = int(
                datetime.fromisoformat(manifest["started_at"]).timestamp()
            )
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    "CREATE TABLE log (time INTEGER, task TEXT, level TEXT, message TEXT)"
                )
                connection.execute(
                    "INSERT INTO log VALUES (?, '{}', 'INFO', 'inside')",
                    (event_second,),
                )
                connection.commit()
            finally:
                connection.close()

            report = analyze_window(
                log_dir, manifest=manifest, database_path=database_path
            )

        self.assertEqual(report["metrics"]["sqlite_rows"], 1)

    def test_capture_window_excludes_old_bytes_and_measures_process(self):
        old_line = b"2026-08-11 09:00:00,000 old.py:1 INFO run: old\n"
        new_line = b"2026-08-11 10:00:00,000 new.py:2 INFO run: new\n"
        manifest = {
            "window_id": "capture-probe",
            "phase": "before",
            "environment": {
                "simulator": "probe",
                "account_fingerprint": "probe-account",
                "resolution": "1x1",
                "performance_profile": "probe",
                "mower_config_fingerprint": "sha256:probe",
                "code_revision": "deadbeef",
                "log_config_fingerprint": "sha256:probe-log",
            },
            "workload": {
                "infrastructure_read": True,
                "shift_completed": True,
                "native_agent_rounds": 3,
                "maa_completed": True,
                "maa_duration_seconds": 0,
                "webui_connected_throughout": True,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live_log_dir = root / "live-log"
            live_log_dir.mkdir()
            (live_log_dir / "runtime.log").write_bytes(old_line)
            database_path = root / "data.db"
            script_path = root / "producer.py"
            script_path.write_text(
                "\n".join(
                    [
                        "import sqlite3, sys, time",
                        "from pathlib import Path",
                        "print('probe')",
                        "Path(sys.argv[1]).open('ab').write(" + repr(new_line) + ")",
                        "connection = sqlite3.connect(sys.argv[2])",
                        "connection.execute('CREATE TABLE log (time INTEGER, task TEXT, level TEXT, message TEXT)')",
                        "connection.execute('INSERT INTO log VALUES (?, ?, ?, ?)', (int(time.time()), '{}', 'INFO', 'new'))",
                        "connection.commit()",
                        "connection.close()",
                        "sum(value * value for value in range(500000))",
                        "time.sleep(0.1)",
                    ]
                ),
                encoding="utf-8",
            )
            output_dir = root / "capture"
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            capture_exit_code = main(
                [
                    "capture",
                    "--live-log-dir",
                    str(live_log_dir),
                    "--database",
                    str(database_path),
                    "--output-dir",
                    str(output_dir),
                    "--manifest",
                    str(manifest_path),
                    "--poll-interval",
                    "0.01",
                    "--",
                    sys.executable,
                    str(script_path),
                    str(live_log_dir / "runtime.log"),
                    str(database_path),
                ]
            )

            captured_bytes = (output_dir / "log" / "runtime.log").read_bytes()
            captured_stdout = (
                (output_dir / "stdout.log").read_bytes()
                if (output_dir / "stdout.log").is_file()
                else b""
            )
            report = json.loads(
                (output_dir / "report.json").read_text(encoding="utf-8")
            )
            written_manifest = json.loads(
                (output_dir / "manifest.json").read_text(encoding="utf-8")
            )

        self.assertEqual(
            {
                "captured_bytes": captured_bytes,
                "captured_stdout": b"probe" in captured_stdout,
                "capture_exit_code": capture_exit_code,
                "logical_records": report["totals"]["logical_records"],
                "process_exit_code": report["process_exit_code"],
                "sqlite_rows": report["metrics"]["sqlite_rows"],
                "cold_start": written_manifest["workload"]["cold_start"],
                "normal_exit": written_manifest["workload"]["normal_exit"],
                "has_cpu_metric": report["metrics"]["cpu_seconds"] >= 0,
                "has_rss_metric": report["metrics"]["peak_rss_bytes"] > 0,
            },
            {
                "captured_bytes": new_line,
                "captured_stdout": True,
                "capture_exit_code": 2,
                "logical_records": 1,
                "process_exit_code": 0,
                "sqlite_rows": 1,
                "cold_start": True,
                "normal_exit": True,
                "has_cpu_metric": True,
                "has_rss_metric": True,
            },
        )

    def test_freeze_ledger_rejects_redundant_pareto_gap_row(self):
        reports = [
            _ledger_report(
                index,
                [
                    _pareto_row("core.py:1", "core", 95, 950),
                    _pareto_row("gap.py:2", "gap", 1, 10, level="INFO"),
                ],
            )
            for index in range(1, 4)
        ]

        ledger = freeze_ledger(
            reports,
            [
                _ledger_row("core.py:1", "core"),
                _ledger_row(
                    "gap.py:2", "gap", selection_basis="pareto_gap", level="INFO"
                ),
            ],
        )

        self.assertEqual(
            ledger["validity"],
            {
                "valid": False,
                "reasons": ["ledger row 2 is a redundant pareto_gap selection"],
            },
        )

    def test_freeze_ledger_accepts_consistency_rows_after_coverage_cutoff(self):
        reports = [
            _ledger_report(
                index,
                [
                    _pareto_row("core.py:1", "core", 95, 950),
                    _pareto_row("tail.py:2", "tail", 5, 50),
                ],
            )
            for index in range(1, 4)
        ]

        ledger = freeze_ledger(
            reports,
            [
                _ledger_row("core.py:1", "core"),
                _ledger_row(
                    "tail.py:2",
                    "tail",
                    selection_basis="scope_consistency",
                ),
            ],
        )

        self.assertEqual(ledger["validity"], {"valid": True, "reasons": []})
        self.assertEqual(ledger["residual_pareto"]["recommended_selectors"], [])
        self.assertEqual(ledger["coverage"][0]["record_ratio"], 1.0)
        self.assertEqual(ledger["coverage"][0]["byte_ratio"], 1.0)

    def test_freeze_ledger_selects_smallest_stable_residual_set(self):
        pareto_rows = (
            ("base.py:1", "base", 80, 800),
            ("high.py:2", "high", 15, 150),
            ("low.py:3", "low_one", 5, 50),
            ("low.py:4", "low_two", 5, 50),
            ("low.py:5", "low_three", 5, 50),
        )
        reports = [
            _ledger_report(
                index,
                [
                    _pareto_row(source, function, count, byte_count)
                    for source, function, count, byte_count in pareto_rows
                ],
            )
            for index in range(1, 4)
        ]

        declaration = [
            _ledger_row("base.py:1", "base"),
            _ledger_row(
                "high.py:2",
                "high",
                target_message_shape="<unchanged>",
                decision="exclude",
                change="none",
                selection_basis="pareto_gap",
            ),
            _ledger_row("low.py:3", "low_one", selection_basis="pareto_gap"),
            _ledger_row("low.py:4", "low_two", selection_basis="pareto_gap"),
            _ledger_row("low.py:5", "low_three", selection_basis="pareto_gap"),
        ]

        ledger = freeze_ledger(reports, declaration)

        self.assertIn(
            "ledger pareto_gap selection is not the smallest stable residual set",
            ledger["validity"]["reasons"],
        )
        self.assertEqual(
            ledger["residual_pareto"],
            {
                "stable_candidate_count": 4,
                "out_of_scope": [],
                "recommended_selectors": [
                    {
                        "source": "high.py:2",
                        "function": "high",
                        "level": "DEBUG",
                        "message_shape": "high",
                    }
                ],
            },
        )

    def test_freeze_ledger_rejects_unclassified_stable_residual(self):
        reports = [
            _ledger_report(
                index,
                [
                    _pareto_row("base.py:1", "base", 80, 800),
                    _pareto_row("unknown.py:2", "unknown", 20, 200),
                ],
            )
            for index in range(1, 4)
        ]

        ledger = freeze_ledger(reports, [_ledger_row("base.py:1", "base")])

        self.assertIn(
            "stable residual selector unknown.py:2/unknown/DEBUG/unknown requires "
            "a ledger row or out_of_scope rule",
            ledger["validity"]["reasons"],
        )

    def test_freeze_ledger_excludes_classified_out_of_scope_residual(self):
        reports = [
            _ledger_report(
                index,
                [
                    _pareto_row("base.py:1", "base", 80, 800),
                    _pareto_row("unknown.py:2", "unknown", 20, 200),
                ],
            )
            for index in range(1, 4)
        ]
        rules = [
            {
                "source": r"unknown\.py:2",
                "function": "unknown",
                "level": "DEBUG",
                "message_shape": "unknown",
                "reason": "not one of the six source categories",
            }
        ]

        ledger = freeze_ledger(reports, [_ledger_row("base.py:1", "base")], rules)

        self.assertEqual(
            ledger["residual_pareto"],
            {
                "stable_candidate_count": 0,
                "out_of_scope": [
                    {
                        "source": "unknown.py:2",
                        "function": "unknown",
                        "level": "DEBUG",
                        "message_shape": "unknown",
                        "rule_index": 1,
                        "reason": "not one of the six source categories",
                    }
                ],
                "recommended_selectors": None,
            },
        )

    def test_analyze_cli_writes_invalid_report_and_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_dir = root / "log"
            log_dir.mkdir()
            (log_dir / "runtime.log").write_bytes(
                b"2026-08-11 10:00:00,000 solver.py:10 INFO run: started\n"
            )
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "window_id": "too-short",
                        "phase": "before",
                        "started_at": "2026-08-11T10:00:00+08:00",
                        "ended_at": "2026-08-11T10:01:00+08:00",
                    }
                ),
                encoding="utf-8",
            )
            output_path = root / "report.json"

            exit_code = main(
                [
                    "analyze",
                    "--log-dir",
                    str(log_dir),
                    "--manifest",
                    str(manifest_path),
                    "--output",
                    str(output_path),
                ]
            )
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(
            {
                "exit_code": exit_code,
                "schema_version": report["schema_version"],
                "window_id": report["window"]["window_id"],
                "valid": report["validity"]["valid"],
            },
            {
                "exit_code": 2,
                "schema_version": 1,
                "window_id": "too-short",
                "valid": False,
            },
        )

    def test_message_shapes_remove_dynamic_object_values(self):
        first = (
            "2026-08-11 10:00:00,000 scheduler.py:20 DEBUG plan: "
            "plan {'room_1_1': ['Alice', 'Bob']}\n"
        ).encode()
        second = (
            "2026-08-11 10:00:01,000 scheduler.py:20 DEBUG plan: "
            "plan {'room_2_1': ['Carol']}\n"
        ).encode()
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            (log_dir / "runtime.log").write_bytes(first + second)

            report = analyze_window(log_dir)

        self.assertEqual(
            report["pareto"],
            [
                {
                    "source": "scheduler.py:20",
                    "function": "plan",
                    "level": "DEBUG",
                    "message_shape": "plan <object>",
                    "count": 2,
                    "actual_file_bytes": len(first + second),
                    "record_ratio": 1.0,
                    "byte_ratio": 1.0,
                    "cumulative_record_ratio": 1.0,
                    "cumulative_byte_ratio": 1.0,
                }
            ],
        )

    def test_complete_log_directory_counts_traceback_as_one_record(self):
        log_bytes = (
            b"2026-08-11 10:00:00,000 solver.py:10 INFO run: started 42\r\n"
            b"2026-08-11 10:00:01,000 solver.py:11 ERROR run: failed id=17\r\n"
            b"Traceback (most recent call last):\r\n"
            b'  File "solver.py", line 11, in run\r\n'
            b"ValueError: boom 17\r\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            (log_dir / "runtime.log").write_bytes(log_bytes)

            report = analyze_window(log_dir)

        self.assertEqual(
            {
                "totals": report["totals"],
                "pareto": report["pareto"],
            },
            {
                "totals": {
                    "actual_file_bytes": len(log_bytes),
                    "logical_records": 2,
                    "bytes_per_record": len(log_bytes) / 2,
                    "unparsed_bytes": 0,
                },
                "pareto": [
                    {
                        "source": "solver.py:11",
                        "function": "run",
                        "level": "ERROR",
                        "message_shape": "failed id=<num> | exceptions=ValueError",
                        "count": 1,
                        "actual_file_bytes": 156,
                        "record_ratio": 0.5,
                        "byte_ratio": 0.7255813953488372,
                        "cumulative_record_ratio": 0.5,
                        "cumulative_byte_ratio": 0.7255813953488372,
                    },
                    {
                        "source": "solver.py:10",
                        "function": "run",
                        "level": "INFO",
                        "message_shape": "started <num>",
                        "count": 1,
                        "actual_file_bytes": 59,
                        "record_ratio": 0.5,
                        "byte_ratio": 0.2744186046511628,
                        "cumulative_record_ratio": 1.0,
                        "cumulative_byte_ratio": 1.0,
                    },
                ],
            },
        )

    def test_window_report_validates_workload_and_counts_sqlite_window(self):
        manifest = {
            "window_id": "before-1",
            "phase": "before",
            "started_at": "2026-08-11T10:00:00+08:00",
            "ended_at": "2026-08-11T12:00:00+08:00",
            "environment": {
                "simulator": "mumu-12-daily",
                "account_fingerprint": "account-a",
                "resolution": "1920x1080",
                "performance_profile": "4c6g-60fps",
                "mower_config_fingerprint": "sha256:config",
                "code_revision": "deadbeef",
                "log_config_fingerprint": "sha256:log-config",
            },
            "workload": {
                "cold_start": True,
                "infrastructure_read": True,
                "shift_completed": True,
                "native_agent_rounds": 3,
                "maa_completed": False,
                "maa_duration_seconds": 600,
                "webui_connected_throughout": True,
                "normal_exit": True,
            },
            "metrics": {
                "cpu_seconds": 125.5,
                "peak_rss_bytes": 268_435_456,
            },
        }
        log_line = b"2026-08-11 10:30:00,000 solver.py:10 INFO run: completed\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_dir = root / "log"
            log_dir.mkdir()
            (log_dir / "runtime.log").write_bytes(log_line)
            database_path = root / "data.db"
            started_at = datetime.fromisoformat(manifest["started_at"]).timestamp()
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    "CREATE TABLE log (time INTEGER, task TEXT, level TEXT, message TEXT)"
                )
                connection.executemany(
                    "INSERT INTO log VALUES (?, ?, ?, ?)",
                    [
                        (started_at + 60, '{"id":1}', "INFO", "inside"),
                        (started_at - 60, '{"id":0}', "ERROR", "outside"),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            report = analyze_window(
                log_dir, manifest=manifest, database_path=database_path
            )

        self.assertEqual(
            {
                "window": report["window"],
                "validity": report["validity"],
                "metrics": report["metrics"],
            },
            {
                "window": {
                    "window_id": "before-1",
                    "phase": "before",
                    "started_at": "2026-08-11T10:00:00+08:00",
                    "ended_at": "2026-08-11T12:00:00+08:00",
                    "duration_seconds": 7200.0,
                    "environment": manifest["environment"],
                    "workload": manifest["workload"],
                },
                "validity": {"valid": True, "reasons": []},
                "metrics": {
                    "cpu_seconds": 125.5,
                    "peak_rss_bytes": 268_435_456,
                    "sqlite_rows": 1,
                    "sqlite_logical_text_bytes": 18,
                },
            },
        )

    def test_freeze_ledger_requires_dual_95_percent_in_each_window(self):
        reports = [
            _ledger_report(
                index,
                [
                    _pareto_row(
                        "recognize.py:10", "find", core_count, core_bytes, "find: <str>"
                    ),
                    _pareto_row(
                        "scheduler.py:20",
                        "poll",
                        gap_count,
                        gap_bytes,
                        "still running",
                        level="INFO",
                    ),
                ],
            )
            for index, (core_count, core_bytes, gap_count, gap_bytes) in enumerate(
                ((90, 900, 5, 50), (91, 905, 4, 46), (89, 895, 6, 57)),
                start=1,
            )
        ]
        declaration = [
            _ledger_row(
                "recognize.py:10",
                "find",
                message_shape="find: <str>",
                category="visual_device_core",
            ),
            _ledger_row(
                "scheduler.py:20",
                "poll",
                message_shape="still running",
                target_message_shape=(
                    "task={task_type} elapsed_seconds={elapsed_seconds}"
                ),
                change="progress_summary",
                bounded_fields=[
                    {"name": "task_type", "kind": "string", "max_length": 32},
                    {
                        "name": "elapsed_seconds",
                        "kind": "integer",
                        "minimum": 0,
                        "maximum": 7500,
                    },
                ],
                selection_basis="pareto_gap",
                level="INFO",
            ),
        ]

        ledger = freeze_ledger(reports, declaration)

        self.assertEqual(
            {
                "validity": ledger["validity"],
                "coverage": ledger["coverage"],
                "gap_windows": ledger["rows"][1]["windows"],
            },
            {
                "validity": {"valid": True, "reasons": []},
                "coverage": [
                    {
                        "window_id": "before-1",
                        "record_ratio": 0.95,
                        "byte_ratio": 0.95,
                    },
                    {
                        "window_id": "before-2",
                        "record_ratio": 0.95,
                        "byte_ratio": 0.951,
                    },
                    {
                        "window_id": "before-3",
                        "record_ratio": 0.95,
                        "byte_ratio": 0.952,
                    },
                ],
                "gap_windows": {
                    "before-1": {"count": 5, "actual_file_bytes": 50},
                    "before-2": {"count": 4, "actual_file_bytes": 46},
                    "before-3": {"count": 6, "actual_file_bytes": 57},
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
