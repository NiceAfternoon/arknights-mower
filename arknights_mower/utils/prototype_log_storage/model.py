"""Pure state model for a THROWAWAY log-lifecycle decision prototype.

Question: can fixed, transparent age/value strategies preserve useful history
without a per-instance byte quota, while making irreversible compaction and
manual cleanup visible to the user?

This is planning evidence only. It is not production log storage.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Literal


Strategy = Literal["detail", "balanced", "space"]
Resolution = Literal["detail", "15m", "hour", "day"]


@dataclass(frozen=True)
class StrategyProfile:
    key: Strategy
    label: str
    detail_days: int


PROFILES: dict[Strategy, StrategyProfile] = {
    "detail": StrategyProfile("detail", "细节优先", 7),
    "balanced": StrategyProfile("balanced", "均衡", 3),
    "space": StrategyProfile("space", "空间优先", 1),
}

RESOLUTION_RANK: dict[Resolution, int] = {
    "detail": 0,
    "15m": 1,
    "hour": 2,
    "day": 3,
}


@dataclass(frozen=True)
class LevelCount:
    level: str
    logical: int
    persisted: int
    aggregated: int
    dropped: int = 0


@dataclass(frozen=True)
class DayRecord:
    day: datetime
    resolution: Resolution
    detailed_mib: float
    has_incident: bool
    incident_full: bool
    levels: tuple[LevelCount, ...]
    tasks_ok: int
    tasks_failed: int
    suppressed_events: int

    def stored_mib(self) -> float:
        summary_mib = {
            "detail": self.detailed_mib,
            "15m": 0.10,
            "hour": 0.04,
            "day": 0.008,
        }[self.resolution]
        incident_mib = 0.0
        if self.has_incident:
            incident_mib = 0.75 if self.incident_full else 0.004
        return summary_mib + incident_mib


@dataclass(frozen=True)
class CleanupPreview:
    days: int
    full_incidents: int
    summaries: int
    reclaim_mib: float


@dataclass(frozen=True)
class QueryResult:
    requested_day: datetime
    resolution: Resolution | None
    headline: str
    level_lines: tuple[str, ...]


@dataclass(frozen=True)
class LifecycleState:
    now: datetime
    strategy: Strategy
    days: tuple[DayRecord, ...] = ()
    pending_cleanup: CleanupPreview | None = None
    last_query: QueryResult | None = None
    last_action: str = "prototype started"


def new_state(strategy: Strategy = "balanced") -> LifecycleState:
    return LifecycleState(
        now=datetime(2026, 8, 11, tzinfo=timezone.utc),
        strategy=strategy,
    )


def total_stored_mib(state: LifecycleState) -> float:
    # catalog.json and active-file bookkeeping are represented by a small base.
    return 0.05 + sum(day.stored_mib() for day in state.days)


def _desired_resolution(
    now: datetime, day: datetime, profile: StrategyProfile
) -> Resolution:
    age_days = (now.date() - day.date()).days
    if age_days >= 180:
        return "day"
    if age_days >= 30:
        return "hour"
    if age_days >= profile.detail_days:
        return "15m"
    return "detail"


def _compact(state: LifecycleState) -> LifecycleState:
    profile = PROFILES[state.strategy]
    compacted = []
    for day in state.days:
        desired = _desired_resolution(state.now, day.day, profile)
        # Compaction is irreversible: switching to a more detailed strategy
        # cannot recreate already-discarded rows.
        resolution = max(
            (day.resolution, desired), key=lambda value: RESOLUTION_RANK[value]
        )
        incident_full = day.has_incident and (
            state.now.date() - day.day.date()
        ).days < 30
        compacted.append(
            replace(day, resolution=resolution, incident_full=incident_full)
        )
    return replace(state, days=tuple(compacted))


def add_day(state: LifecycleState, noisy: bool = False) -> LifecycleState:
    if noisy:
        levels = (
            LevelCount("DEBUG", 180_432, 512, 179_920),
            LevelCount("INFO", 1_283, 1_120, 163),
            LevelCount("WARNING", 12, 12, 0),
            LevelCount("ERROR", 2, 2, 0),
            LevelCount("CRITICAL", 0, 0, 0),
        )
        record = DayRecord(
            day=state.now,
            resolution="detail",
            detailed_mib=12.0,
            has_incident=True,
            incident_full=True,
            levels=levels,
            tasks_ok=31,
            tasks_failed=2,
            suppressed_events=179_920,
        )
    else:
        levels = (
            LevelCount("DEBUG", 16_400, 640, 15_760),
            LevelCount("INFO", 920, 900, 20),
            LevelCount("WARNING", 1, 1, 0),
            LevelCount("ERROR", 0, 0, 0),
            LevelCount("CRITICAL", 0, 0, 0),
        )
        record = DayRecord(
            day=state.now,
            resolution="detail",
            detailed_mib=4.0,
            has_incident=False,
            incident_full=False,
            levels=levels,
            tasks_ok=32,
            tasks_failed=0,
            suppressed_events=15_780,
        )
    state = replace(
        state,
        now=state.now + timedelta(days=1),
        days=state.days + (record,),
        pending_cleanup=None,
        last_query=None,
        last_action=("added noisy day" if noisy else "added normal day"),
    )
    return _compact(state)


def seed_history(state: LifecycleState, days: int = 210) -> LifecycleState:
    for index in range(days):
        state = add_day(state, noisy=index % 37 == 0)
    return replace(state, last_action=f"seeded {days} days of unattended history")


def cycle_strategy(state: LifecycleState) -> LifecycleState:
    strategies: tuple[Strategy, ...] = ("detail", "balanced", "space")
    index = (strategies.index(state.strategy) + 1) % len(strategies)
    previous_resolutions = tuple(day.resolution for day in state.days)
    state = _compact(
        replace(
            state,
            strategy=strategies[index],
            pending_cleanup=None,
            last_query=None,
        )
    )
    irreversible = any(
        RESOLUTION_RANK[after.resolution] > RESOLUTION_RANK[before]
        for after, before in zip(state.days, previous_resolutions)
    )
    note = "older data compacted; switching back cannot restore detail" if irreversible else "no existing data needed coarsening"
    return replace(
        state,
        last_action=f"switched to {PROFILES[state.strategy].label}: {note}",
    )


def query_days_ago(state: LifecycleState, days_ago: int = 90) -> LifecycleState:
    requested = state.now - timedelta(days=days_ago)
    record = next(
        (day for day in state.days if day.day.date() == requested.date()), None
    )
    if record is None:
        query = QueryResult(
            requested_day=requested,
            resolution=None,
            headline="该日期没有已保存的数据",
            level_lines=(),
        )
    else:
        headline = (
            f"完成任务 {record.tasks_ok} 个，失败 {record.tasks_failed} 个；"
            f"聚合/抑制 {record.suppressed_events} 个重复事件；"
            f"故障上下文={'完整胶囊' if record.incident_full else ('错误指纹' if record.has_incident else '无故障')}"
        )
        level_lines = tuple(
            f"{item.level}: logical={item.logical}, persisted={item.persisted}, "
            f"aggregated={item.aggregated}, dropped={item.dropped}"
            for item in record.levels
        )
        query = QueryResult(
            requested_day=requested,
            resolution=record.resolution,
            headline=headline,
            level_lines=level_lines,
        )
    return replace(
        state,
        pending_cleanup=None,
        last_query=query,
        last_action=f"queried {days_ago} days ago",
    )


def preview_manual_cleanup(state: LifecycleState) -> LifecycleState:
    preview = CleanupPreview(
        days=len(state.days),
        full_incidents=sum(day.incident_full for day in state.days),
        summaries=sum(day.resolution != "detail" for day in state.days),
        reclaim_mib=total_stored_mib(state),
    )
    return replace(
        state,
        pending_cleanup=preview,
        last_query=None,
        last_action="cleanup preview opened; no data deleted",
    )


def confirm_manual_cleanup(state: LifecycleState) -> LifecycleState:
    if state.pending_cleanup is None:
        return replace(state, last_action="cleanup confirmation ignored: preview first")
    return replace(
        state,
        days=(),
        pending_cleanup=None,
        last_query=None,
        last_action="second confirmation accepted; historical logs deleted",
    )
