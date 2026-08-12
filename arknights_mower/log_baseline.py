import argparse
import copy
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import time
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from arknights_mower.log_baseline_ledger import freeze_ledger

LOG_HEADER_RE = re.compile(
    rb"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
    rb"(?P<source>.+):(?P<line>\d+) "
    rb"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL) "
    rb"(?P<function>[^:]+): ?(?P<message>.*?)(?:\r?\n)?$"
)
EXCEPTION_TYPE_RE = re.compile(
    r"^\s*(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Warning))(?::|$)",
    re.MULTILINE,
)
NUMBER_RE = re.compile(r"(?<![\w])[-+]?(?:\d+\.\d+|\d+)(?![\w])")
OBJECT_RE = re.compile(r"\{.*\}")
LIST_RE = re.compile(r"\[.*\]")
REQUIRED_ENVIRONMENT = (
    "simulator",
    "account_fingerprint",
    "resolution",
    "performance_profile",
    "mower_config_fingerprint",
    "code_revision",
    "log_config_fingerprint",
)


@dataclass(frozen=True)
class _ParsedLogRecord:
    source: str
    function: str
    level: str
    message: str
    header_bytes: int


def _sha256_prefix(path: Path, size: int) -> str:
    digest = hashlib.sha256()
    remaining = size
    with path.open("rb") as stream:
        while remaining:
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
    if remaining:
        raise RuntimeError(f"{path} became shorter while it was being measured")
    return digest.hexdigest()


def _snapshot_logs(log_dir: Path) -> dict[str, dict]:
    snapshot = {}
    for path in Path(log_dir).glob("runtime.log*"):
        if not path.is_file():
            continue
        size = path.stat().st_size
        snapshot[path.name] = {
            "size": size,
            "sha256": _sha256_prefix(path, size)
            if path.name == "runtime.log"
            else None,
        }
    return snapshot


def _extract_log_delta(
    live_log_dir: Path, output_log_dir: Path, snapshot: dict[str, dict]
) -> None:
    output_log_dir.mkdir(parents=True, exist_ok=True)
    active_before = snapshot.get("runtime.log")
    for path in sorted(Path(live_log_dir).glob("runtime.log*")):
        if not path.is_file():
            continue
        size = path.stat().st_size
        start = 0
        before = snapshot.get(path.name)
        if before is not None:
            if path.name != "runtime.log":
                if size != before["size"]:
                    raise RuntimeError(
                        f"rotated log changed during capture: {path.name}"
                    )
                continue
            if (
                size >= before["size"]
                and _sha256_prefix(path, before["size"]) == before["sha256"]
            ):
                start = before["size"]
        elif (
            active_before is not None
            and size >= active_before["size"]
            and _sha256_prefix(path, active_before["size"]) == active_before["sha256"]
        ):
            start = active_before["size"]

        if size <= start:
            continue
        with path.open("rb") as source:
            source.seek(start)
            (output_log_dir / path.name).write_bytes(source.read())


def _descendant_pids(root_pid: int, parent_by_pid: dict[int, int]) -> set[int]:
    children_by_pid = defaultdict(list)
    for pid, parent_pid in parent_by_pid.items():
        children_by_pid[parent_pid].append(pid)
    descendants = set()
    pending = [root_pid]
    while pending:
        pid = pending.pop()
        if pid in descendants:
            continue
        descendants.add(pid)
        pending.extend(children_by_pid.get(pid, ()))
    return descendants


def _windows_process_tree_metrics(
    root_pid: int,
) -> dict[tuple[int, int], tuple[float, int]]:
    import ctypes
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32W),
    ]
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32W),
    ]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    ]

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    parent_by_pid = {}
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while has_entry:
            parent_by_pid[entry.th32ProcessID] = entry.th32ParentProcessID
            has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)

    def filetime_ticks(value):
        ticks = value.dwLowDateTime | (value.dwHighDateTime << 32)
        return ticks

    metrics = {}
    process_access = 0x0400 | 0x0010
    for pid in _descendant_pids(root_pid, parent_by_pid):
        handle = kernel32.OpenProcess(process_access, False, pid)
        if not handle:
            continue
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                continue
            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            ):
                continue
            identity = (pid, filetime_ticks(creation))
            cpu_seconds = (filetime_ticks(kernel) + filetime_ticks(user)) / 10_000_000
            metrics[identity] = (cpu_seconds, counters.WorkingSetSize)
        finally:
            kernel32.CloseHandle(handle)
    return metrics


def _proc_process_tree_metrics(
    root_pid: int,
) -> dict[tuple[int, int], tuple[float, int]]:
    clock_ticks = os.sysconf("SC_CLK_TCK")
    page_size = os.sysconf("SC_PAGE_SIZE")
    parent_by_pid = {}
    values_by_pid = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            stat = (path / "stat").read_text(encoding="ascii")
            fields = stat[stat.rfind(")") + 2 :].split()
            pid = int(path.name)
            parent_by_pid[pid] = int(fields[1])
            values_by_pid[pid] = (
                int(fields[19]),
                (int(fields[11]) + int(fields[12])) / clock_ticks,
                int(fields[21]) * page_size,
            )
        except (FileNotFoundError, ProcessLookupError):
            continue
    metrics = {}
    for pid in _descendant_pids(root_pid, parent_by_pid):
        if pid not in values_by_pid:
            continue
        started_at_ticks, cpu_seconds, rss_bytes = values_by_pid[pid]
        metrics[(pid, started_at_ticks)] = (cpu_seconds, rss_bytes)
    return metrics


class _ProcessSampler:
    def __init__(self, process: subprocess.Popen):
        self.process = process
        self.cpu_seconds = 0.0
        self.peak_rss_bytes = 0
        self._cpu_by_process = {}

    def sample(self) -> None:
        try:
            if os.name == "nt":
                metrics = _windows_process_tree_metrics(self.process.pid)
            elif Path(f"/proc/{self.process.pid}/stat").is_file():
                metrics = _proc_process_tree_metrics(self.process.pid)
            else:
                return
        except (FileNotFoundError, OSError, ProcessLookupError):
            return
        current_rss_bytes = 0
        for identity, (cpu_seconds, rss_bytes) in metrics.items():
            self._cpu_by_process[identity] = max(
                self._cpu_by_process.get(identity, 0.0), cpu_seconds
            )
            current_rss_bytes += rss_bytes
        self.cpu_seconds = sum(self._cpu_by_process.values())
        self.peak_rss_bytes = max(self.peak_rss_bytes, current_rss_bytes)


def _backup_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        closing(sqlite3.connect(source)) as source_connection,
        closing(sqlite3.connect(destination)) as destination_connection,
    ):
        source_connection.backup(destination_connection)


def capture_window(
    *,
    command: list[str],
    live_log_dir: Path,
    database_path: Path,
    output_dir: Path,
    manifest: dict,
    poll_interval: float = 0.25,
) -> dict:
    if not command:
        raise ValueError("capture command must not be empty")
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f"capture output already exists: {output_dir}")

    snapshot = _snapshot_logs(live_log_dir)
    output_dir.mkdir(parents=True)
    started_at = datetime.now().astimezone()
    with (
        (output_dir / "stdout.log").open("wb") as stdout,
        (output_dir / "stderr.log").open("wb") as stderr,
    ):
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        sampler = _ProcessSampler(process)
        while process.poll() is None:
            sampler.sample()
            time.sleep(poll_interval)
        process_exit_code = process.wait()
        sampler.sample()
    ended_at = datetime.now().astimezone()

    _extract_log_delta(live_log_dir, output_dir / "log", snapshot)
    captured_database = output_dir / "data.db"
    if Path(database_path).is_file():
        _backup_database(Path(database_path), captured_database)

    resolved_manifest = copy.deepcopy(manifest)
    resolved_manifest["started_at"] = started_at.isoformat()
    resolved_manifest["ended_at"] = ended_at.isoformat()
    workload = resolved_manifest.setdefault("workload", {})
    workload["cold_start"] = True
    workload["normal_exit"] = process_exit_code == 0
    resolved_manifest["metrics"] = {
        "cpu_seconds": sampler.cpu_seconds,
        "peak_rss_bytes": sampler.peak_rss_bytes,
    }
    _write_json(output_dir / "manifest.json", resolved_manifest)

    report = analyze_window(
        output_dir / "log",
        manifest=resolved_manifest,
        database_path=captured_database,
    )
    report["command"] = command
    report["process_exit_code"] = process_exit_code
    _write_json(output_dir / "report.json", report)
    return report


def _message_shape(message: str, continuation: bytes) -> str:
    shape = OBJECT_RE.sub("<object>", message)
    shape = LIST_RE.sub("<list>", shape)
    shape = NUMBER_RE.sub("<num>", shape)
    exception_types = list(
        dict.fromkeys(
            match.group("type")
            for match in EXCEPTION_TYPE_RE.finditer(
                continuation.decode("utf-8", errors="replace")
            )
        )
    )
    if exception_types:
        shape += f" | exceptions={','.join(exception_types)}"
    return shape


def _window_details(
    manifest: dict, database_path: Path | None
) -> tuple[dict, dict, dict]:
    reasons = []
    try:
        started_at = datetime.fromisoformat(manifest["started_at"])
        ended_at = datetime.fromisoformat(manifest["ended_at"])
        if started_at.utcoffset() is None or ended_at.utcoffset() is None:
            reasons.append("started_at and ended_at must include a UTC offset")
        duration_seconds = (ended_at - started_at).total_seconds()
    except (KeyError, TypeError, ValueError):
        started_at = None
        ended_at = None
        duration_seconds = 0.0
        reasons.append("started_at and ended_at must be valid ISO-8601 timestamps")

    if duration_seconds < 7200:
        reasons.append("window duration must be at least 7200 seconds")
    if duration_seconds > 7500:
        reasons.append("window duration must not exceed 7500 seconds")

    environment = manifest.get("environment", {})
    for field in REQUIRED_ENVIRONMENT:
        if not environment.get(field):
            reasons.append(f"environment.{field} is required")

    workload = manifest.get("workload", {})
    for field in (
        "cold_start",
        "infrastructure_read",
        "shift_completed",
        "webui_connected_throughout",
        "normal_exit",
    ):
        if workload.get(field) is not True:
            reasons.append(f"workload.{field} must be true")
    if workload.get("native_agent_rounds", 0) < 3:
        reasons.append("workload.native_agent_rounds must be at least 3")
    if not (
        workload.get("maa_completed") is True
        or workload.get("maa_duration_seconds", 0) >= 600
    ):
        reasons.append("MAA must complete normally or run for at least 600 seconds")

    supplied_metrics = manifest.get("metrics", {})
    for field in ("cpu_seconds", "peak_rss_bytes"):
        if supplied_metrics.get(field, 0) <= 0:
            reasons.append(f"metrics.{field} must be greater than zero")

    sqlite_rows = 0
    sqlite_text_bytes = 0
    if database_path is None or not Path(database_path).is_file():
        reasons.append("a SQLite database snapshot is required")
    elif started_at is not None and ended_at is not None:
        with closing(sqlite3.connect(database_path)) as connection:
            try:
                rows = connection.execute(
                    "SELECT task, level, message FROM log WHERE time >= ? AND time < ?",
                    (
                        math.floor(started_at.timestamp()),
                        math.ceil(ended_at.timestamp()),
                    ),
                )
                for row in rows:
                    sqlite_rows += 1
                    sqlite_text_bytes += sum(
                        len(str(value or "").encode("utf-8")) for value in row
                    )
            except sqlite3.OperationalError:
                reasons.append("SQLite database must contain the log table")

    window = {
        "window_id": manifest.get("window_id"),
        "phase": manifest.get("phase"),
        "started_at": manifest.get("started_at"),
        "ended_at": manifest.get("ended_at"),
        "duration_seconds": duration_seconds,
        "environment": environment,
        "workload": workload,
    }
    metrics = {
        "cpu_seconds": supplied_metrics.get("cpu_seconds"),
        "peak_rss_bytes": supplied_metrics.get("peak_rss_bytes"),
        "sqlite_rows": sqlite_rows,
        "sqlite_logical_text_bytes": sqlite_text_bytes,
    }
    return window, {"valid": not reasons, "reasons": reasons}, metrics


def analyze_window(
    log_dir: Path,
    *,
    manifest: dict | None = None,
    database_path: Path | None = None,
) -> dict:
    log_dir = Path(log_dir)
    files = sorted(path for path in log_dir.glob("runtime.log*") if path.is_file())
    groups = defaultdict(lambda: {"count": 0, "actual_file_bytes": 0})
    total_bytes = 0
    logical_records = 0
    unparsed_bytes = 0

    for path in files:
        total_bytes += path.stat().st_size
        current = None
        continuation = bytearray()

        def finish_current():
            nonlocal current, continuation, logical_records
            if current is None:
                return
            message_shape = _message_shape(current.message, bytes(continuation))
            key = (current.source, current.function, current.level, message_shape)
            group = groups[key]
            group["count"] += 1
            group["actual_file_bytes"] += current.header_bytes + len(continuation)
            logical_records += 1
            current = None
            continuation = bytearray()

        with path.open("rb") as stream:
            for raw_line in stream:
                match = LOG_HEADER_RE.match(raw_line)
                if match:
                    finish_current()
                    source = match.group("source").decode("utf-8", errors="replace")
                    source = source.replace("\\", "/")
                    current = _ParsedLogRecord(
                        source=f"{source}:{match.group('line').decode('ascii')}",
                        function=match.group("function").decode(
                            "utf-8", errors="replace"
                        ),
                        level=match.group("level").decode("ascii"),
                        message=match.group("message").decode(
                            "utf-8", errors="replace"
                        ),
                        header_bytes=len(raw_line),
                    )
                elif current is None:
                    unparsed_bytes += len(raw_line)
                else:
                    continuation.extend(raw_line)
        finish_current()

    pareto = []
    for key, values in groups.items():
        source, function, level, message_shape = key
        pareto.append(
            {
                "source": source,
                "function": function,
                "level": level,
                "message_shape": message_shape,
                **values,
            }
        )
    pareto.sort(
        key=lambda item: (
            -item["actual_file_bytes"],
            -item["count"],
            item["source"],
            item["function"],
            item["message_shape"],
        )
    )
    cumulative_records = 0
    cumulative_bytes = 0
    for item in pareto:
        cumulative_records += item["count"]
        cumulative_bytes += item["actual_file_bytes"]
        item.update(
            {
                "record_ratio": item["count"] / logical_records
                if logical_records
                else 0.0,
                "byte_ratio": item["actual_file_bytes"] / total_bytes
                if total_bytes
                else 0.0,
                "cumulative_record_ratio": cumulative_records / logical_records
                if logical_records
                else 0.0,
                "cumulative_byte_ratio": cumulative_bytes / total_bytes
                if total_bytes
                else 0.0,
            }
        )
    bytes_per_record = total_bytes / logical_records if logical_records else 0.0
    report = {
        "schema_version": 1,
        "totals": {
            "actual_file_bytes": total_bytes,
            "logical_records": logical_records,
            "bytes_per_record": bytes_per_record,
            "unparsed_bytes": unparsed_bytes,
        },
        "pareto": pareto,
    }
    if manifest is not None:
        window, validity, metrics = _window_details(manifest, database_path)
        report.update({"window": window, "validity": validity, "metrics": metrics})
    return report


def _read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure representative Mower log windows and freeze a call-site ledger."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    capture_parser = commands.add_parser(
        "capture", help="run Mower and capture one isolated log window"
    )
    capture_parser.add_argument("--live-log-dir", required=True, type=Path)
    capture_parser.add_argument("--database", required=True, type=Path)
    capture_parser.add_argument("--output-dir", required=True, type=Path)
    capture_parser.add_argument("--manifest", required=True, type=Path)
    capture_parser.add_argument("--poll-interval", type=float, default=0.25)
    capture_parser.add_argument("capture_command", nargs=argparse.REMAINDER)

    analyze_parser = commands.add_parser(
        "analyze", help="analyze one complete log window"
    )
    analyze_parser.add_argument("--log-dir", required=True, type=Path)
    analyze_parser.add_argument("--manifest", required=True, type=Path)
    analyze_parser.add_argument("--database", type=Path)
    analyze_parser.add_argument("--output", required=True, type=Path)

    freeze_parser = commands.add_parser(
        "freeze", help="verify three reports and enrich the declared ledger"
    )
    freeze_parser.add_argument("--report", action="append", required=True, type=Path)
    freeze_parser.add_argument("--declaration", required=True, type=Path)
    freeze_parser.add_argument("--output", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.command == "capture":
        command = args.capture_command
        if command[:1] == ["--"]:
            command = command[1:]
        report = capture_window(
            command=command,
            live_log_dir=args.live_log_dir,
            database_path=args.database,
            output_dir=args.output_dir,
            manifest=_read_json(args.manifest),
            poll_interval=args.poll_interval,
        )
        if report["process_exit_code"]:
            return report["process_exit_code"]
        return 0 if report["validity"]["valid"] else 2

    if args.command == "analyze":
        report = analyze_window(
            args.log_dir,
            manifest=_read_json(args.manifest),
            database_path=args.database,
        )
        _write_json(args.output, report)
        return 0 if report["validity"]["valid"] else 2

    reports = [_read_json(path) for path in args.report]
    declaration_payload = _read_json(args.declaration)
    declaration = (
        declaration_payload.get("rows", [])
        if isinstance(declaration_payload, dict)
        else declaration_payload
    )
    out_of_scope_rules = (
        declaration_payload.get("out_of_scope_rules", [])
        if isinstance(declaration_payload, dict)
        else []
    )
    ledger = freeze_ledger(reports, declaration, out_of_scope_rules)
    _write_json(args.output, ledger)
    return 0 if ledger["validity"]["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
