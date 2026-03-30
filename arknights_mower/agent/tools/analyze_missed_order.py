import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from arknights_mower.utils.path import get_path

MISSED_ORDER_TYPE = "漏单"
DIRECT_MISS_KEYWORDS = ("检测到漏单", "上一个订单漏单", "漏单")
CONTEXT_KEYWORDS = (
    "等待跑单",
    "下一次进行插拔的时间",
    "当前",
    "订单",
    "移除超过15分钟的跑单任务",
    "移除15分钟内的跑单任务",
    "跳过",
    "清除",
    "移除",
    "skip",
    "clear",
    "remove",
)
SCHEDULER_TASK_RE = re.compile(
    r"SchedulerTask\(time='(?P<time>[^']+)',task_plan=.*?,task_type=TaskTypes\."
    r"(?P<task_type>\w+),meta_data='(?P<meta_data>[^']*)'(?:,adjusted="
    r"(?P<adjusted>True|False))?\)",
    re.DOTALL,
)
logger = logging.getLogger(__name__)


def _database_path():
    return get_path("@app/tmp/data.db")


def _connect(database_path=None):
    return sqlite3.connect(database_path or _database_path())


def _parse_local_time(time_str: str) -> datetime:
    time_str = time_str.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析时间: {time_str}")


def _parse_scheduler_time(time_str: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue
    return None


def fetch_missed_orders(limit: int = 10, database_path=None) -> list[dict]:
    conn = _connect(database_path)
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT
                strftime('%Y-%m-%d %H:%M:%S', time, 'unixepoch', 'localtime') AS local_time,
                type,
                price
            FROM trading_history
            WHERE type = ?
            ORDER BY time DESC
            LIMIT ?
            """,
            (MISSED_ORDER_TYPE, limit),
        )
        rows = cursor.fetchall()
        return [
            {"local_time": row[0], "type": row[1], "price": row[2], "index": idx + 1}
            for idx, row in enumerate(rows)
        ]
    finally:
        cursor.close()
        conn.close()


def fetch_logs_in_window(start_ts: int, end_ts: int, database_path=None) -> list[dict]:
    conn = _connect(database_path)
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT
                time,
                strftime('%Y-%m-%d %H:%M:%S', time, 'unixepoch', 'localtime') AS local_time,
                task,
                level,
                message
            FROM log
            WHERE time BETWEEN ? AND ?
            ORDER BY time ASC
            """,
            (start_ts, end_ts),
        )
        rows = cursor.fetchall()
        return [
            {
                "time": row[0],
                "local_time": row[1],
                "task": row[2] or "",
                "level": row[3] or "",
                "message": row[4] or "",
            }
            for row in rows
        ]
    finally:
        cursor.close()
        conn.close()


def extract_scheduler_tasks(text: str, source_time: Optional[str] = None) -> list[dict]:
    if not text:
        return []
    tasks = []
    for match in SCHEDULER_TASK_RE.finditer(text):
        planned_at = _parse_scheduler_time(match.group("time"))
        if planned_at is None:
            continue
        tasks.append(
            {
                "planned_time": planned_at.strftime("%Y-%m-%d %H:%M:%S"),
                "planned_at": planned_at,
                "task_type": match.group("task_type"),
                "room": match.group("meta_data"),
                "adjusted": match.group("adjusted") == "True",
                "source_time": source_time,
            }
        )
    return tasks


def extract_run_order_candidates(log_rows: list[dict]) -> list[dict]:
    candidates = []
    seen = set()
    for row in log_rows:
        for source_field in ("task", "message"):
            extracted = extract_scheduler_tasks(row.get(source_field, ""), row["local_time"])
            for task in extracted:
                if task["task_type"] != "RUN_ORDER":
                    continue
                key = (task["planned_time"], task["room"], row["local_time"], source_field)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        **task,
                        "log_time": row["local_time"],
                        "log_level": row["level"],
                        "source_field": source_field,
                    }
                )
    candidates.sort(key=lambda item: (item["planned_at"], item["log_time"]))
    return candidates


def select_primary_run_order(target_time: datetime, candidates: list[dict]) -> Optional[dict]:
    eligible = [item for item in candidates if item["planned_at"] <= target_time]
    if not eligible:
        return None
    eligible.sort(key=lambda item: (item["planned_at"], item["log_time"]), reverse=True)
    return eligible[0]


def detect_log_gap(log_rows: list[dict], expected_start: datetime, expected_end: datetime) -> dict:
    if not log_rows:
        return {"has_gap": True, "reason": "window_empty"}
    datetimes = [
        _parse_local_time(row["local_time"])
        for row in log_rows
        if row.get("local_time")
    ]
    if not datetimes:
        return {"has_gap": True, "reason": "window_empty"}
    max_gap = timedelta()
    for prev, curr in zip(datetimes, datetimes[1:]):
        gap = curr - prev
        if gap > max_gap:
            max_gap = gap
    edge_gap = max(datetimes[0] - expected_start, expected_end - datetimes[-1], max_gap)
    return {
        "has_gap": edge_gap >= timedelta(minutes=30),
        "max_gap_minutes": round(edge_gap.total_seconds() / 60, 1),
    }


def extract_context_signals(
    log_rows: list[dict], room: Optional[str], time_b: Optional[datetime], time_c: datetime
) -> dict:
    direct = []
    indirect = []
    error_logs = []
    keep_indices = set()
    room = room or ""
    for idx, row in enumerate(log_rows):
        text = f"{row['task']} {row['message']}"
        if row["level"] == "ERROR":
            error_logs.append(row)
            keep_indices.update({idx, max(0, idx - 1)})
        if any(keyword in text for keyword in DIRECT_MISS_KEYWORDS):
            direct.append(row)
            keep_indices.update({idx, max(0, idx - 1)})
        if "TaskTypes.RUN_ORDER" in text or "run_order" in text or (room and room in text):
            indirect.append(row)
            keep_indices.add(idx)
        if any(keyword in text for keyword in CONTEXT_KEYWORDS):
            keep_indices.update({idx, max(0, idx - 1)})
    timeline = [log_rows[idx] for idx in sorted(keep_indices)]
    if time_b is not None:
        timeline = [
            row
            for row in timeline
            if _parse_local_time(row["local_time"]) >= time_b - timedelta(minutes=30)
            and _parse_local_time(row["local_time"]) <= time_c
        ] or timeline
    return {
        "direct_miss_signals": direct[:20],
        "indirect_miss_signals": indirect[:40],
        "error_logs": error_logs[:20],
        "timeline_logs": timeline[:80],
    }


def infer_candidate_causes(
    room: Optional[str],
    primary_task: Optional[dict],
    all_candidates: list[dict],
    room_timeline: list[dict],
    context_signals: dict,
    gap_info: dict,
    target_time: datetime,
) -> list[dict]:
    causes = []
    if context_signals["direct_miss_signals"]:
        causes.append(
            {
                "type": "direct_miss_detected",
                "confidence": "high",
                "reason": "日志中直接出现漏单提示",
            }
        )
    if context_signals["error_logs"] and primary_task is not None:
        causes.append(
            {
                "type": "execution_failed",
                "confidence": "medium",
                "reason": "时间B附近存在 ERROR 日志",
            }
        )
    adjusted_timeline = [item for item in room_timeline if item["adjusted"]]
    if adjusted_timeline:
        causes.append(
            {
                "type": "task_delayed",
                "confidence": "medium",
                "reason": "同房间 RUN_ORDER 任务存在 adjusted=True，可能发生延后",
            }
        )
    if primary_task is not None and not context_signals["direct_miss_signals"]:
        if gap_info.get("has_gap"):
            causes.append(
                {
                    "type": "software_not_running",
                    "confidence": "medium",
                    "reason": "时间B附近日志存在明显断档，疑似软件未运行或未正常记录",
                }
            )
        else:
            room_events_after_b = [
                item
                for item in room_timeline
                if item["planned_at"] > primary_task["planned_at"]
                and item["planned_at"] <= target_time
            ]
            if not room_events_after_b:
                causes.append(
                    {
                        "type": "task_skipped_or_cleared",
                        "confidence": "low",
                        "reason": "找到时间B的跑单任务，但后续同房间任务链中断",
                    }
                )
    if primary_task is None:
        if not all_candidates and gap_info.get("has_gap"):
            causes.append(
                {
                    "type": "software_not_running",
                    "confidence": "medium",
                    "reason": "时间C前的窗口里几乎没有有效日志，也没有 RUN_ORDER 任务证据",
                }
            )
        elif not all_candidates:
            causes.append(
                {
                    "type": "insufficient_evidence",
                    "confidence": "low",
                    "reason": "窗口内没有找到任何 RUN_ORDER 任务证据，无法定位时间B",
                }
            )
        else:
            causes.append(
                {
                    "type": "insufficient_evidence",
                    "confidence": "low",
                    "reason": "窗口内只看到与时间C不匹配的 RUN_ORDER 计划，无法锁定同房间的时间B",
                }
            )
    if not causes:
        causes.append(
            {
                "type": "insufficient_evidence",
                "confidence": "low",
                "reason": "已找到部分线索，但证据不足以闭环判断",
            }
        )
    return causes


def build_analysis_payload(
    room: Optional[str],
    target_time: datetime,
    time_a: Optional[datetime],
    time_b: Optional[datetime],
    room_timeline: list[dict],
    context_signals: dict,
    candidate_causes: list[dict],
) -> dict:
    return {
        "room": room,
        "time_a": time_a.strftime("%Y-%m-%d %H:%M:%S") if time_a else None,
        "time_b": time_b.strftime("%Y-%m-%d %H:%M:%S") if time_b else None,
        "time_c": target_time.strftime("%Y-%m-%d %H:%M:%S"),
        "run_order_timeline": [
            {
                "planned_time": item["planned_time"],
                "room": item["room"],
                "adjusted": item["adjusted"],
                "log_time": item["log_time"],
            }
            for item in room_timeline[:20]
        ],
        "timeline_logs": [
            {
                "time": row["local_time"],
                "level": row["level"],
                "task": row["task"],
                "message": row["message"][:400],
            }
            for row in context_signals["timeline_logs"]
        ],
        "candidate_causes": candidate_causes,
    }


def _analyze_target_time(
    target_time: datetime,
    window_start_hours: float,
    window_end_hours: float,
    database_path=None,
) -> dict:
    search_start = target_time - timedelta(hours=window_start_hours)
    search_end = target_time - timedelta(hours=window_end_hours)
    if search_end > target_time:
        search_end = target_time
    log_rows = fetch_logs_in_window(
        int(search_start.timestamp()),
        int(search_end.timestamp()),
        database_path=database_path,
    )
    candidates = extract_run_order_candidates(log_rows)
    primary_task = select_primary_run_order(target_time, candidates)
    room = primary_task["room"] if primary_task else None
    room_timeline = [item for item in candidates if room and item["room"] == room]
    room_timeline.sort(key=lambda item: (item["planned_at"], item["log_time"]))
    time_b = primary_task["planned_at"] if primary_task else None
    time_a = room_timeline[0]["planned_at"] if room_timeline else None
    context_signals = extract_context_signals(log_rows, room, time_b, target_time)
    gap_info = detect_log_gap(
        log_rows,
        time_b - timedelta(minutes=20) if time_b else search_start,
        target_time,
    )
    candidate_causes = infer_candidate_causes(
        room,
        primary_task,
        candidates,
        room_timeline,
        context_signals,
        gap_info,
        target_time,
    )
    return {
        "target_time": target_time.strftime("%Y-%m-%d %H:%M:%S"),
        "candidate_room": room,
        "time_a": time_a.strftime("%Y-%m-%d %H:%M:%S") if time_a else None,
        "time_b": time_b.strftime("%Y-%m-%d %H:%M:%S") if time_b else None,
        "time_c": target_time.strftime("%Y-%m-%d %H:%M:%S"),
        "search_window": {
            "start": search_start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": search_end.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "run_order_task": primary_task,
        "run_order_snapshots": room_timeline[:30],
        "timeline_logs": context_signals["timeline_logs"],
        "direct_miss_signals": context_signals["direct_miss_signals"],
        "indirect_miss_signals": context_signals["indirect_miss_signals"],
        "candidate_causes": candidate_causes,
        "log_gap": gap_info,
        "analysis_payload": build_analysis_payload(
            room,
            target_time,
            time_a,
            time_b,
            room_timeline,
            context_signals,
            candidate_causes,
        ),
    }


def analyze_missed_order(
    mode: str,
    order_time: Optional[str] = None,
    event_time: Optional[str] = None,
    window_start_hours: float = 2.5,
    window_end_hours: float = 0.0,
):
    try:
        if mode == "list_orders":
            orders = fetch_missed_orders()
            return json.dumps(
                {
                    "mode": mode,
                    "has_orders": bool(orders),
                    "count": len(orders),
                    "orders": orders,
                },
                ensure_ascii=False,
            )
        if mode == "analyze_by_order":
            if not order_time:
                raise ValueError("analyze_by_order 需要 order_time")
            target_time = _parse_local_time(order_time)
            result = _analyze_target_time(
                target_time, window_start_hours, window_end_hours
            )
            result["mode"] = mode
            return json.dumps(result, ensure_ascii=False)
        if mode == "analyze_by_time":
            if not event_time:
                raise ValueError("analyze_by_time 需要 event_time")
            target_time = _parse_local_time(event_time)
            result = _analyze_target_time(
                target_time, window_start_hours, window_end_hours
            )
            result["mode"] = mode
            return json.dumps(result, ensure_ascii=False)
        raise ValueError(f"未知 mode: {mode}")
    except Exception as e:
        logger.exception(e)
        return json.dumps(
            {"mode": mode, "error": str(e)},
            ensure_ascii=False,
        )


analyze_missed_order_tool_def = {
    "type": "function",
    "function": {
        "name": "analyze_missed_order",
        "description": (
            "专门用于分析跑单漏单原因。"
            "当用户要排查漏单原因时，优先使用这个工具，而不是自己拼 SQL。"
            "list_orders 用于列出漏单订单；analyze_by_order 用于按选中的漏单订单分析；"
            "analyze_by_time 用于用户直接给出漏单时间时分析。"
            "工具返回 JSON 字符串。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["list_orders", "analyze_by_order", "analyze_by_time"],
                    "description": "执行模式",
                },
                "order_time": {
                    "type": "string",
                    "description": "漏单订单时间，格式 YYYY-MM-DD HH:MM:SS",
                },
                "event_time": {
                    "type": "string",
                    "description": "用户直接提供的漏单发生时间，格式 YYYY-MM-DD HH:MM:SS",
                },
                "window_start_hours": {
                    "type": "number",
                    "description": "向前回溯多少小时，默认 2.5",
                },
                "window_end_hours": {
                    "type": "number",
                    "description": "距离目标时间的截断小时数，默认 0.0",
                },
            },
            "required": ["mode"],
        },
    },
}
