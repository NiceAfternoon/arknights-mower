import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from arknights_mower.utils import log as log_module

LOG_LINE = (
    "{timestamp},000 arknights_mower\\tests\\logging_compatibility_tests.py:1 "
    "INFO contract: {message}\n"
)
WEBSOCKET_CONTRACT_PATH = (
    Path(__file__).parents[2] / "ui" / "src" / "stores" / "websocket-log-contract.json"
)


def write_log(path: Path, *records: tuple[str, str]) -> None:
    path.write_text(
        "".join(
            LOG_LINE.format(timestamp=timestamp, message=message)
            for timestamp, message in records
        ),
        encoding="utf-8",
    )


def run_isolated_python(script: str, data_dir: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["MOWER_DATA_DIR"] = str(data_dir)
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[2],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


@contextmanager
def capture_log_messages():
    records = []

    class CaptureHandler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    capture_handler = CaptureHandler()
    log_module.logger.addHandler(capture_handler)
    try:
        yield records
    finally:
        log_module.logger.removeHandler(capture_handler)


class PublicLoggerCompatibilityTests(unittest.TestCase):
    def test_public_logger_writes_utf8_envelope_and_hourly_rotation_names(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            log_dir = data_dir / "log"
            log_dir.mkdir()
            runtime_log = log_dir / "runtime.log"
            runtime_log.touch()
            base_time = datetime(2026, 8, 17, 10).timestamp()
            os.utime(runtime_log, (base_time, base_time))
            result = run_isolated_python(
                """
from datetime import datetime
from unittest.mock import patch

base_time = datetime(2026, 8, 17, 10).timestamp()
with patch("logging.handlers.time.time", return_value=base_time):
    from arknights_mower.utils.log import log_queue, logger
    logger.info("公共入口第一小时")
    log_queue.join()
with patch("logging.handlers.time.time", return_value=base_time + 3601):
    logger.warning("公共入口第二小时")
    log_queue.join()
""",
                data_dir,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            files = sorted(path.name for path in log_dir.iterdir())
            self.assertEqual(
                files,
                ["runtime.log", "runtime.log.2026-08-17_10"],
            )
            contents = "".join(
                path.read_text(encoding="utf-8") for path in sorted(log_dir.iterdir())
            )
            self.assertRegex(
                contents,
                re.compile(
                    r"^2026-08-17 10:00:00,000 <string>:\d+ INFO <module>: "
                    r"公共入口第一小时$",
                    re.MULTILINE,
                ),
            )
            with patch.object(log_module, "get_path", return_value=log_dir):
                queried_logs = log_module.get_log_by_time(datetime(2026, 8, 17, 10, 30))
            self.assertEqual(
                [path.name for path in queried_logs],
                ["runtime.log.2026-08-17_10", "runtime.log"],
            )

            from arknights_mower.utils.email import Email

            email = Email("<p>链路反馈</p>", "Mower Bug", None, queried_logs)
            attached_payloads = {
                part.get_filename(): part.get_payload(decode=True)
                for part in email.msg.walk()
                if part.get_filename()
            }
            self.assertEqual(
                attached_payloads,
                {path.name: path.read_bytes() for path in queried_logs},
            )
            self.assertRegex(
                contents,
                re.compile(
                    r"^2026-08-17 11:00:01,000 <string>:\d+ WARNING <module>: "
                    r"公共入口第二小时$",
                    re.MULTILINE,
                ),
            )

    def test_public_logger_process_exits_normally_with_runtime_log_available(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            result = run_isolated_python(
                """
from arknights_mower.utils.log import logger

logger.info("normal-exit-contract")
""",
                data_dir,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            runtime_log = data_dir / "log" / "runtime.log"
            self.assertTrue(runtime_log.is_file())
            self.assertIn(
                "normal-exit-contract", runtime_log.read_text(encoding="utf-8")
            )

    def test_normal_mower_stop_completes_and_keeps_public_logger_available(self):
        import server
        from arknights_mower.solvers import record as record_module
        from arknights_mower.utils import config

        class StoppableThread:
            def __init__(self):
                self.alive = True

            def join(self, timeout):
                self.alive = not config.stop_mower.is_set()

            def is_alive(self):
                return self.alive

        original_thread = server.mower_thread
        thread = StoppableThread()
        server.mower_thread = thread
        config.stop_mower.clear()
        headers = {"token": getattr(server.app, "token", "")}
        try:
            with (
                patch.object(record_module, "current_state", return_value={}) as state,
                patch.object(record_module, "save_state_to_db") as save,
                patch.object(server, "set_mower_thread") as set_thread,
                capture_log_messages() as records,
            ):
                response = server.app.test_client().get("/stop", headers=headers)
                log_module.logger.info("post-normal-stop-contract")

            self.assertEqual(response.get_data(as_text=True), "true")
            self.assertFalse(thread.is_alive())
            self.assertIsNone(server.mower_thread)
            self.assertTrue(config.stop_mower.is_set())
            state.assert_called_once_with()
            save.assert_called_once_with({})
            set_thread.assert_called_once_with(None)
            self.assertIn("成功停止mower线程", records)
            self.assertIn("post-normal-stop-contract", records)
        finally:
            server.mower_thread = original_thread
            config.stop_mower.clear()


class LogTimeQueryContractTests(unittest.TestCase):
    def test_returns_cross_hour_and_active_files_by_content_time_in_stable_order(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_dir = Path(tmp_dir)
            first = log_dir / "runtime.log.segment-a"
            second = log_dir / "runtime.log.segment-b"
            active = log_dir / "runtime.log"
            misleading = log_dir / "runtime.log.2026-08-17_12"
            write_log(
                first,
                ("2026-08-17 10:59:59", "before-hour"),
                ("2026-08-17 11:00:01", "first-hour"),
            )
            write_log(
                second,
                ("2026-08-17 11:59:59", "cross-hour"),
                ("2026-08-17 12:00:01", "second-hour"),
            )
            write_log(active, ("2026-08-17 12:30:00", "active"))
            write_log(misleading, ("2026-08-17 08:00:00", "outside-window"))

            with patch.object(log_module, "get_path", return_value=log_dir):
                result = log_module.get_log_by_time(datetime(2026, 8, 17, 12))

            self.assertEqual(result, [first, second, active])

    def test_custom_range_includes_every_intermediate_hour(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_dir = Path(tmp_dir)
            expected = []
            for hour in range(10, 15):
                path = log_dir / f"runtime.log.2026-08-17_{hour:02d}"
                write_log(path, (f"2026-08-17 {hour:02d}:00:00", f"hour-{hour}"))
                expected.append(path)

            with patch.object(log_module, "get_path", return_value=log_dir):
                result = log_module.get_log_by_time(
                    datetime(2026, 8, 17, 12), time_range=2
                )

            self.assertEqual(result, expected)

    def test_timestamp_like_continuation_is_not_a_file_record_bound(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_dir = Path(tmp_dir)
            unrelated = log_dir / "runtime.log.segment"
            write_log(unrelated, ("2026-08-17 08:00:00", "outside-window"))
            with unrelated.open("a", encoding="utf-8") as stream:
                stream.write("2026-08-17 12:00:00,000 traceback continuation\n")

            with patch.object(log_module, "get_path", return_value=log_dir):
                result = log_module.get_log_by_time(datetime(2026, 8, 17, 12))

            self.assertEqual(result, [])


class FeedbackCompatibilityTests(unittest.TestCase):
    def test_feedback_attaches_raw_logs_without_logging_the_full_body(self):
        from arknights_mower.agent.tools import submit_issue as submit_module

        secret_body = "用户完整反馈 SECRET-FEEDBACK-BODY 期望与实际行为"
        with capture_log_messages() as records:
            with tempfile.TemporaryDirectory() as tmp_dir:
                raw_log = Path(tmp_dir) / "runtime.log"
                raw_bytes = "原始日志\nsecond line\n".encode("utf-8")
                raw_log.write_bytes(raw_bytes)
                with (
                    patch.object(
                        submit_module, "get_log_by_time", return_value=[raw_log]
                    ) as get_logs,
                    patch.object(submit_module, "Email") as email_class,
                    redirect_stdout(io.StringIO()) as stdout,
                ):
                    result = submit_module.submit_issue(
                        secret_body,
                        "Bug",
                        "2026-08-17 11:55:00",
                        "2026-08-17 12:05:00",
                    )

                self.assertEqual(result, "问题已成功上报，感谢您的反馈！")
                get_logs.assert_called_once_with(datetime(2026, 8, 17, 12, 5))
                email_args = email_class.call_args.args
                self.assertIn(secret_body, email_args[0])
                self.assertEqual(
                    email_class.call_args.kwargs["attach_files"], [raw_log]
                )
                self.assertEqual(raw_log.read_bytes(), raw_bytes)
                email_class.return_value.send.assert_called_once_with(
                    ["354013233@qq.com"]
                )
                self.assertNotIn(secret_body, "\n".join(records))
                self.assertNotIn(secret_body, stdout.getvalue())

    def test_email_attachment_preserves_the_raw_text_file(self):
        from arknights_mower.utils.email import Email

        with tempfile.TemporaryDirectory() as tmp_dir:
            raw_log = Path(tmp_dir) / "runtime.log.2026-08-17_12"
            raw_bytes = "第一行\r\ntraceback continuation\r\n".encode("utf-8")
            raw_log.write_bytes(raw_bytes)

            email = Email(
                "<p>正常反馈正文</p>",
                "Mower Bug",
                None,
                attach_files=[raw_log],
            )

            attachments = [part for part in email.msg.walk() if part.get_filename()]
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0].get_filename(), raw_log.name)
            self.assertEqual(attachments[0].get_payload(decode=True), raw_bytes)

    def test_feedback_http_boundary_forwards_body_without_logging_it(self):
        import server
        from arknights_mower.agent.tools import submit_issue as submit_module

        secret_body = "HTTP SECRET-FEEDBACK-BODY 期望与实际行为"
        with capture_log_messages() as records:
            request_body = {
                "type": "Bug",
                "startTime": datetime(2026, 8, 17, 11, 55).timestamp() * 1000,
                "endTime": datetime(2026, 8, 17, 12, 5).timestamp() * 1000,
                "description": secret_body,
            }
            with (
                server.app.test_request_context(json=request_body),
                patch.object(
                    submit_module,
                    "submit_issue",
                    return_value="邮件发送成功！",
                ) as submit,
            ):
                result = server.submit_feedback.__wrapped__()

            self.assertEqual(result, "邮件发送成功！")
            submit.assert_called_once_with(
                secret_body,
                "Bug",
                "2026-08-17 11:55:00",
                "2026-08-17 12:05:00",
            )
            self.assertNotIn(secret_body, "\n".join(records))


class WebSocketLogCompatibilityTests(unittest.TestCase):
    def test_public_logger_live_websocket_payload_matches_frontend_contract(self):
        import server

        contract = json.loads(WEBSOCKET_CONTRACT_PATH.read_text(encoding="utf-8"))

        class CapturingWebSocket:
            def __init__(self):
                self.payloads = []

            def send(self, payload):
                self.payloads.append(json.loads(payload))

        websocket = CapturingWebSocket()
        server.ws_connections.append(websocket)
        try:
            fixed_time = datetime(2026, 8, 15, 12).timestamp()
            with patch("time.time", return_value=fixed_time):
                log_module.logger.info(
                    "operation=scene result=index\ntraceback continuation"
                )

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                matching = [
                    payload
                    for payload in websocket.payloads
                    if "operation=scene result=index" in payload.get("data", "")
                ]
                if matching:
                    break
                time.sleep(0.01)
            else:
                self.fail("public logger record did not reach a live websocket")
        finally:
            server.ws_connections.remove(websocket)

        self.assertEqual(
            matching[-1],
            {"type": "log", "data": contract["backendData"]},
        )

    def test_public_logger_websocket_history_keeps_exactly_the_latest_100_lines(self):
        from simple_websocket import ConnectionClosed

        import server

        server.log_lines = []
        lines = [f"ws-contract-line-{index}" for index in range(105)]
        console_level = log_module.dhlr.level
        log_module.dhlr.setLevel(logging.CRITICAL)
        try:
            log_module.logger.info("%s\n", "\n".join(lines))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if any("ws-contract-line-104" in line for line in server.log_lines):
                    break
                time.sleep(0.01)
            else:
                self.fail("public logger record did not reach the websocket history")
        finally:
            log_module.dhlr.setLevel(console_level)

        class FakeWebSocket:
            def __init__(self):
                self.sent = []

            def send(self, payload):
                self.sent.append(payload)

            def receive(self):
                raise ConnectionClosed()

        websocket = FakeWebSocket()
        server.app.view_functions["log"].__wrapped__(websocket)
        payload = json.loads(websocket.sent[0])
        history = payload["data"].splitlines()

        self.assertEqual(len(history), 100)
        self.assertEqual(history[0], "ws-contract-line-5")
        self.assertEqual(history[-1], "ws-contract-line-104")


if __name__ == "__main__":
    unittest.main()
