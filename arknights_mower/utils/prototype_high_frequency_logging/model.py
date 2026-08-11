"""Pure model for a THROWAWAY high-frequency logging policy prototype.

Question: which recognition/device observations become authority records,
bounded aggregates, ephemeral breadcrumbs, frozen incident entries, or weak
frame references when a retry recovers or finally fails?

This is planning evidence only. It performs no logging, I/O, image capture, or
production measurement.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

Family = Literal["color", "resource", "match", "screenshot", "input", "adb"]
Module = Literal["recognition", "device"]
Outcome = Literal["succeeded", "not_matched", "attempt_failed"]


@dataclass(frozen=True)
class FamilyPolicy:
    family: Family
    module: Module
    event_name: str
    sample_every: int


FAMILY_POLICIES: dict[Family, FamilyPolicy] = {
    "color": FamilyPolicy("color", "recognition", "recognition.color.compared", 100),
    "resource": FamilyPolicy(
        "resource", "recognition", "recognition.resource.looked_up", 100
    ),
    "match": FamilyPolicy("match", "recognition", "recognition.match.evaluated", 100),
    "screenshot": FamilyPolicy(
        "screenshot", "device", "device.screenshot.captured", 20
    ),
    "input": FamilyPolicy("input", "device", "device.input.executed", 1),
    "adb": FamilyPolicy("adb", "device", "device.adb.command.executed", 1),
}


@dataclass(frozen=True)
class Policy:
    first_window_seconds: int = 5 * 60
    steady_window_seconds: int = 15 * 60
    aggregate_key_limit: int = 256
    summary_top_groups: int = 10
    ring_max_seconds: int = 30
    ring_max_entries: int = 64
    frame_pre: int = 2
    frame_post: int = 2


@dataclass(frozen=True)
class AggregateStat:
    family: Family
    operation_key: str
    outcome: Outcome
    count: int = 0
    sampled: int = 0
    duration_total_ms: int = 0
    duration_max_ms: int = 0


@dataclass(frozen=True)
class Breadcrumb:
    breadcrumb_id: int
    at_second: int
    event_name: str
    operation_key: str
    outcome: str
    ordinal: int
    reason: str


@dataclass(frozen=True)
class FrameCandidate:
    frame_id: int
    at_second: int
    role: str
    persisted: bool = False


@dataclass(frozen=True)
class FrameArtifactRef:
    ref: str
    role: str
    sensitivity: str = "S2"
    retention: str = "weak/expires"


@dataclass(frozen=True)
class FrameGroup:
    group_ref: str
    reason: str
    frames: tuple[FrameArtifactRef, ...]


@dataclass(frozen=True)
class Incident:
    incident_ref: str
    reason: str
    breadcrumbs: tuple[Breadcrumb, ...]
    ring_evicted_before_freeze: int
    frame_group_ref: str | None


@dataclass(frozen=True)
class AuthorityRecord:
    event_seq: int
    event_name: str
    level: str
    message: str
    raw_count: int = 1
    suppressed_count: int = 0
    sampled_count: int = 0
    groups: tuple[str, ...] = ()
    incident_ref: str | None = None
    frame_group_ref: str | None = None


@dataclass(frozen=True)
class PrototypeState:
    policy: Policy
    scenario: str
    now_second: int = 0
    current_scene: str = "INDEX"
    raw_calls: int = 0
    per_call_records_discarded: int = 0
    aggregate_overflow_count: int = 0
    aggregate: tuple[AggregateStat, ...] = ()
    sample_ordinals: tuple[tuple[str, int], ...] = ()
    ring: tuple[Breadcrumb, ...] = ()
    ring_evicted: int = 0
    pre_frames: tuple[FrameCandidate, ...] = ()
    frame_candidates_discarded: int = 0
    frame_groups: tuple[FrameGroup, ...] = ()
    incidents: tuple[Incident, ...] = ()
    authority: tuple[AuthorityRecord, ...] = ()
    next_breadcrumb_id: int = 1
    next_frame_id: int = 1
    next_event_seq: int = 1
    next_incident_id: int = 1
    first_window_done: bool = False
    last_action: str = "prototype started"
    retained: tuple[str, ...] = ()
    discarded: tuple[str, ...] = ()


def new_state(scenario: str = "empty") -> PrototypeState:
    return PrototypeState(policy=Policy(), scenario=scenario)


def _sample_key(family: Family, operation_key: str) -> str:
    return f"{family}:{operation_key}"


def _get_ordinal(state: PrototypeState, key: str) -> int:
    return dict(state.sample_ordinals).get(key, 0)


def _set_ordinal(
    state: PrototypeState, key: str, ordinal: int
) -> tuple[tuple[str, int], ...]:
    values = dict(state.sample_ordinals)
    values[key] = ordinal
    return tuple(sorted(values.items()))


def _trim_ring(
    ring: tuple[Breadcrumb, ...], now_second: int, policy: Policy
) -> tuple[tuple[Breadcrumb, ...], int]:
    cutoff = now_second - policy.ring_max_seconds
    recent = tuple(item for item in ring if item.at_second >= cutoff)
    evicted = len(ring) - len(recent)
    if len(recent) > policy.ring_max_entries:
        evicted += len(recent) - policy.ring_max_entries
        recent = recent[-policy.ring_max_entries :]
    return recent, evicted


def _append_breadcrumb(
    state: PrototypeState,
    *,
    event_name: str,
    operation_key: str,
    outcome: str,
    ordinal: int,
    reason: str,
) -> PrototypeState:
    item = Breadcrumb(
        breadcrumb_id=state.next_breadcrumb_id,
        at_second=state.now_second,
        event_name=event_name,
        operation_key=operation_key,
        outcome=outcome,
        ordinal=ordinal,
        reason=reason,
    )
    ring, evicted = _trim_ring(state.ring + (item,), state.now_second, state.policy)
    return replace(
        state,
        ring=ring,
        ring_evicted=state.ring_evicted + evicted,
        next_breadcrumb_id=state.next_breadcrumb_id + 1,
    )


def _add_aggregate(
    state: PrototypeState,
    *,
    family: Family,
    operation_key: str,
    outcome: Outcome,
    duration_ms: int,
    sampled: bool,
) -> PrototypeState:
    values = list(state.aggregate)
    match_index = next(
        (
            index
            for index, value in enumerate(values)
            if (value.family, value.operation_key, value.outcome)
            == (family, operation_key, outcome)
        ),
        None,
    )
    overflow = state.aggregate_overflow_count
    if match_index is None and len(values) >= state.policy.aggregate_key_limit:
        operation_key = "other"
        overflow += 1
        match_index = next(
            (
                index
                for index, value in enumerate(values)
                if (value.family, value.operation_key, value.outcome)
                == (family, operation_key, outcome)
            ),
            None,
        )
    if match_index is None:
        values.append(
            AggregateStat(
                family=family,
                operation_key=operation_key,
                outcome=outcome,
                count=1,
                sampled=int(sampled),
                duration_total_ms=duration_ms,
                duration_max_ms=duration_ms,
            )
        )
    else:
        current = values[match_index]
        values[match_index] = replace(
            current,
            count=current.count + 1,
            sampled=current.sampled + int(sampled),
            duration_total_ms=current.duration_total_ms + duration_ms,
            duration_max_ms=max(current.duration_max_ms, duration_ms),
        )
    return replace(state, aggregate=tuple(values), aggregate_overflow_count=overflow)


def _capture_pre_frame(state: PrototypeState) -> PrototypeState:
    frame = FrameCandidate(
        frame_id=state.next_frame_id,
        at_second=state.now_second,
        role="pre",
    )
    candidates = state.pre_frames + (frame,)
    discarded = state.frame_candidates_discarded
    if len(candidates) > state.policy.frame_pre:
        discarded += len(candidates) - state.policy.frame_pre
        candidates = candidates[-state.policy.frame_pre :]
    return replace(
        state,
        pre_frames=candidates,
        frame_candidates_discarded=discarded,
        next_frame_id=state.next_frame_id + 1,
    )


def observe_routine(
    state: PrototypeState,
    family: Family,
    operation_key: str,
    *,
    outcome: Outcome = "succeeded",
    duration_ms: int = 8,
    advance_seconds: int = 0,
) -> PrototypeState:
    """Observe one routine call without producing a per-call authority record."""

    policy = FAMILY_POLICIES[family]
    now = state.now_second + advance_seconds
    state = replace(state, now_second=now)
    key = _sample_key(family, operation_key)
    ordinal = _get_ordinal(state, key) + 1
    sampled = ordinal == 1 or ordinal % policy.sample_every == 0
    state = replace(
        state,
        raw_calls=state.raw_calls + 1,
        per_call_records_discarded=state.per_call_records_discarded + 1,
        sample_ordinals=_set_ordinal(state, key, ordinal),
    )
    state = _add_aggregate(
        state,
        family=family,
        operation_key=operation_key,
        outcome=outcome,
        duration_ms=duration_ms,
        sampled=sampled,
    )
    retained = ["aggregate count and bounded duration inputs"]
    discarded = ["routine per-call authority record"]
    if sampled:
        if policy.sample_every == 1:
            reason = "every observation"
        else:
            reason = (
                "first observation"
                if ordinal == 1
                else f"every {policy.sample_every}th"
            )
        state = _append_breadcrumb(
            state,
            event_name=policy.event_name,
            operation_key=operation_key,
            outcome=outcome,
            ordinal=ordinal,
            reason=reason,
        )
        retained.append(f"ephemeral breadcrumb ({reason})")
    else:
        discarded.append("unsampled per-call diagnostic detail")
    if family == "screenshot" and outcome == "succeeded":
        state = _capture_pre_frame(state)
        retained.append("latest two frame candidates in memory")
        discarded.append("older routine frame candidate after overwrite")
    return replace(
        state,
        last_action=f"routine {family}/{operation_key} {outcome} at ordinal {ordinal}",
        retained=tuple(retained),
        discarded=tuple(discarded),
    )


def _append_authority(
    state: PrototypeState,
    *,
    event_name: str,
    level: str,
    message: str,
    raw_count: int = 1,
    suppressed_count: int = 0,
    sampled_count: int = 0,
    groups: tuple[str, ...] = (),
    incident_ref: str | None = None,
    frame_group_ref: str | None = None,
) -> PrototypeState:
    record = AuthorityRecord(
        event_seq=state.next_event_seq,
        event_name=event_name,
        level=level,
        message=message,
        raw_count=raw_count,
        suppressed_count=suppressed_count,
        sampled_count=sampled_count,
        groups=groups,
        incident_ref=incident_ref,
        frame_group_ref=frame_group_ref,
    )
    return replace(
        state,
        authority=state.authority + (record,),
        next_event_seq=state.next_event_seq + 1,
    )


def flush_window(state: PrototypeState) -> PrototypeState:
    """Flush at most one bounded summary per active domain."""

    summary_count = 0
    total_raw = sum(item.count for item in state.aggregate)
    for module in ("recognition", "device"):
        module_stats = [
            item
            for item in state.aggregate
            if FAMILY_POLICIES[item.family].module == module
        ]
        if not module_stats:
            continue
        module_stats.sort(key=lambda item: (-item.count, item.operation_key, item.outcome))
        top = module_stats[: state.policy.summary_top_groups]
        hidden_groups = module_stats[state.policy.summary_top_groups :]
        raw_count = sum(item.count for item in module_stats)
        sampled_count = sum(item.sampled for item in module_stats)
        hidden_count = sum(item.count for item in hidden_groups)
        groups = tuple(
            f"{item.family}/{item.operation_key}/{item.outcome}: count={item.count}, "
            f"sampled={item.sampled}, avg_ms={item.duration_total_ms / item.count:.1f}, "
            f"max_ms={item.duration_max_ms}"
            for item in top
        )
        if hidden_count:
            groups += (f"other displayed groups: count={hidden_count}",)
        state = _append_authority(
            state,
            event_name=f"{module}.activity.summary",
            level="INFO",
            message=f"{module} high-frequency activity aggregated",
            raw_count=raw_count,
            suppressed_count=raw_count,
            sampled_count=sampled_count,
            groups=groups,
        )
        summary_count += 1
    window = (
        state.policy.first_window_seconds
        if not state.first_window_done
        else state.policy.steady_window_seconds
    )
    return replace(
        state,
        now_second=state.now_second + window,
        aggregate=(),
        aggregate_overflow_count=0,
        first_window_done=True,
        last_action=f"flushed {total_raw} calls into {summary_count} domain summaries",
        retained=(f"{summary_count} bounded domain summary record(s)",),
        discarded=(f"{total_raw} per-call authority records", "aggregate bucket after flush"),
    )


def observe_scene(state: PrototypeState, scene: str) -> PrototypeState:
    state = replace(state, raw_calls=state.raw_calls + 1)
    if scene == state.current_scene:
        state = _add_aggregate(
            state,
            family="match",
            operation_key="scene.same",
            outcome="succeeded",
            duration_ms=0,
            sampled=False,
        )
        return replace(
            state,
            per_call_records_discarded=state.per_call_records_discarded + 1,
            last_action=f"re-observed unchanged scene {scene}",
            retained=("unchanged-scene aggregate count",),
            discarded=("duplicate scene INFO",),
        )
    previous = state.current_scene
    state = _append_breadcrumb(
        state,
        event_name="recognition.scene.changed",
        operation_key=f"{previous}->{scene}",
        outcome="changed",
        ordinal=1,
        reason="state boundary",
    )
    state = _append_authority(
        state,
        event_name="recognition.scene.changed",
        level="INFO",
        message=f"scene changed: {previous} -> {scene}",
    )
    return replace(
        state,
        current_scene=scene,
        last_action=f"scene changed from {previous} to {scene}",
        retained=("one immediate INFO with from/to/reason", "diagnostic boundary"),
        discarded=("no duplicate state record",),
    )


def _observe_retry_failure(
    state: PrototypeState,
    *,
    family: Family,
    operation_key: str,
    attempt: int,
) -> PrototypeState:
    state = replace(
        state,
        raw_calls=state.raw_calls + 1,
        per_call_records_discarded=state.per_call_records_discarded + 1,
        now_second=state.now_second + 1,
    )
    state = _add_aggregate(
        state,
        family=family,
        operation_key=operation_key,
        outcome="attempt_failed",
        duration_ms=120 * attempt,
        sampled=True,
    )
    return _append_breadcrumb(
        state,
        event_name=f"{FAMILY_POLICIES[family].module}.{family}.attempt_failed",
        operation_key=operation_key,
        outcome="attempt_failed",
        ordinal=attempt,
        reason="retry evidence",
    )


def retry_recovered(
    state: PrototypeState,
    *,
    family: Family = "screenshot",
    operation_key: str = "mumu12",
    failures: int = 2,
) -> PrototypeState:
    for attempt in range(1, failures + 1):
        state = _observe_retry_failure(
            state, family=family, operation_key=operation_key, attempt=attempt
        )
    state = replace(state, raw_calls=state.raw_calls + 1, now_second=state.now_second + 1)
    state = _append_breadcrumb(
        state,
        event_name=f"{FAMILY_POLICIES[family].module}.{family}.recovered",
        operation_key=operation_key,
        outcome="recovered",
        ordinal=failures + 1,
        reason="recovery boundary",
    )
    state = _append_authority(
        state,
        event_name=f"{FAMILY_POLICIES[family].module}.{family}.recovered",
        level="WARNING",
        message=f"recovered after {failures} failed attempts",
        raw_count=failures + 1,
        suppressed_count=failures,
        sampled_count=failures + 1,
    )
    return replace(
        state,
        last_action=f"{family}/{operation_key} recovered on attempt {failures + 1}",
        retained=("one recovery WARNING", "attempt count and fingerprint summary"),
        discarded=(
            f"{failures} per-attempt authority errors",
            "incident freeze",
            "persisted failure-frame group",
        ),
    )


def _make_frame_group(
    state: PrototypeState,
    *,
    reason: str,
    post_frames: int,
) -> tuple[PrototypeState, FrameGroup]:
    frames = list(state.pre_frames[-state.policy.frame_pre :])
    trigger = FrameCandidate(
        frame_id=state.next_frame_id,
        at_second=state.now_second,
        role="trigger",
        persisted=True,
    )
    frames.append(trigger)
    next_frame = state.next_frame_id + 1
    for _ in range(min(post_frames, state.policy.frame_post)):
        frames.append(
            FrameCandidate(
                frame_id=next_frame,
                at_second=state.now_second + 1,
                role="post",
                persisted=True,
            )
        )
        next_frame += 1
    group_ref = f"artifact://failure-frames/group-{state.next_incident_id:02d}"
    refs = tuple(
        FrameArtifactRef(
            ref=f"artifact://failure-frames/frame-{item.frame_id:04d}",
            role=item.role,
        )
        for item in frames
    )
    group = FrameGroup(group_ref=group_ref, reason=reason, frames=refs)
    return (
        replace(
            state,
            frame_groups=state.frame_groups + (group,),
            next_frame_id=next_frame,
        ),
        group,
    )


def retry_exhausted(
    state: PrototypeState,
    *,
    family: Family = "screenshot",
    operation_key: str = "mumu12",
    failures: int = 3,
    include_frames: bool = True,
    post_frames: int = 2,
) -> PrototypeState:
    for attempt in range(1, failures + 1):
        state = _observe_retry_failure(
            state, family=family, operation_key=operation_key, attempt=attempt
        )
    frame_group = None
    if include_frames:
        state, frame_group = _make_frame_group(
            state,
            reason=f"{family}.{operation_key}.retry_exhausted",
            post_frames=post_frames,
        )
    ring, newly_evicted = _trim_ring(state.ring, state.now_second, state.policy)
    state = replace(
        state,
        ring=ring,
        ring_evicted=state.ring_evicted + newly_evicted,
    )
    incident_ref = f"incident://run/task/failure-{state.next_incident_id:02d}"
    incident = Incident(
        incident_ref=incident_ref,
        reason=f"{family}.{operation_key}.retry_exhausted",
        breadcrumbs=state.ring,
        ring_evicted_before_freeze=state.ring_evicted,
        frame_group_ref=frame_group.group_ref if frame_group else None,
    )
    state = replace(
        state,
        incidents=state.incidents + (incident,),
        next_incident_id=state.next_incident_id + 1,
    )
    state = _append_authority(
        state,
        event_name=f"{FAMILY_POLICIES[family].module}.{family}.failed",
        level="ERROR",
        message=f"retry exhausted after {failures} attempts",
        raw_count=failures,
        suppressed_count=failures,
        sampled_count=failures,
        incident_ref=incident_ref,
        frame_group_ref=frame_group.group_ref if frame_group else None,
    )
    retained = [
        "one final ERROR",
        f"frozen incident chain with {len(incident.breadcrumbs)} entries",
    ]
    if frame_group:
        retained.append(f"one weak frame-group reference with {len(frame_group.frames)} frames")
    return replace(
        state,
        last_action=f"{family}/{operation_key} exhausted {failures} attempts",
        retained=tuple(retained),
        discarded=(
            f"{failures} per-attempt authority errors",
            f"{state.ring_evicted} diagnostic entries outside ring bounds",
            "raw screenshot bytes from LogEvent",
        ),
    )


def success_scenario() -> PrototypeState:
    return replace(
        observe_routine(new_state("successful silence"), "match", "template:confirm"),
        scenario="successful silence",
    )


def sampling_scenario() -> PrototypeState:
    state = new_state("repeated sampling")
    for _ in range(205):
        state = observe_routine(state, "color", "comparator:confirm")
    return replace(
        state,
        scenario="repeated sampling",
        last_action="observed 205 identical color comparisons",
        retained=("aggregate count=205", "breadcrumbs at ordinals 1, 100, 200"),
        discarded=("205 per-call authority records", "202 unsampled diagnostic details"),
    )


def window_scenario() -> PrototypeState:
    state = new_state("window aggregation")
    for _ in range(1200):
        state = observe_routine(state, "match", "template:scene")
    for _ in range(300):
        state = observe_routine(state, "screenshot", "backend:mumu12", duration_ms=24)
    state = flush_window(state)
    return replace(state, scenario="window aggregation")


def state_scenario() -> PrototypeState:
    state = new_state("state change")
    for _ in range(10):
        state = observe_scene(state, "INDEX")
    state = observe_scene(state, "INFRA_MAIN")
    return replace(state, scenario="state change")


def recovered_scenario() -> PrototypeState:
    state = new_state("retry recovered")
    state = observe_routine(state, "screenshot", "backend:mumu12", advance_seconds=1)
    return replace(retry_recovered(state), scenario="retry recovered")


def exhausted_scenario() -> PrototypeState:
    state = new_state("retry exhausted")
    state = observe_scene(state, "INFRA_MAIN")
    state = observe_routine(state, "input", "tap", advance_seconds=1)
    state = observe_routine(state, "screenshot", "backend:mumu12", advance_seconds=1)
    state = observe_routine(state, "screenshot", "backend:mumu12", advance_seconds=1)
    return replace(retry_exhausted(state), scenario="retry exhausted")


def ring_scenario() -> PrototypeState:
    state = new_state("diagnostic ring freeze")
    for index in range(70):
        family: Family = "input" if index % 2 else "adb"
        operation = "tap" if family == "input" else "focus_query"
        state = observe_routine(
            state,
            family,
            operation,
            advance_seconds=1,
        )
    state = retry_exhausted(
        state,
        family="adb",
        operation_key="focus_query",
        include_frames=False,
    )
    return replace(state, scenario="diagnostic ring freeze")


def frames_scenario() -> PrototypeState:
    state = new_state("failure screenshot references")
    for _ in range(4):
        state = observe_routine(
            state,
            "screenshot",
            "backend:mumu12",
            advance_seconds=1,
        )
    state = retry_exhausted(
        state,
        family="screenshot",
        operation_key="backend:mumu12",
        post_frames=2,
    )
    return replace(state, scenario="failure screenshot references")


SCENARIOS = {
    "success": success_scenario,
    "sampling": sampling_scenario,
    "window": window_scenario,
    "state": state_scenario,
    "recovered": recovered_scenario,
    "exhausted": exhausted_scenario,
    "ring": ring_scenario,
    "frames": frames_scenario,
}
