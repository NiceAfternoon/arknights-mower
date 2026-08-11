"""Pure model for the THROWAWAY source-owned logging decision prototype.

Low-level recognition/device primitives return facts. The owner that knows the
final operation outcome decides whether one semantic event is authoritative.
This file performs no logging, I/O, image capture, or production measurement.
"""

from dataclasses import dataclass, replace
from typing import Literal

Method = Literal["color", "template", "feature", "screenshot", "input", "adb"]


@dataclass(frozen=True)
class ProbeFact:
    candidate: str
    method: Method
    matched: bool
    score: float | None
    threshold: float | None
    duration_ms: int
    reason: str

    @property
    def margin(self) -> float:
        if self.score is None or self.threshold is None:
            return float("inf")
        return abs(self.score - self.threshold)

    @property
    def modeled_legacy_fragments(self) -> int:
        return {
            "color": 3,
            "template": 2,
            "feature": 4,
            "screenshot": 2,
            "input": 2,
            "adb": 2,
        }[self.method]


@dataclass(frozen=True)
class AttemptSummary:
    attempt: int
    outcome: str
    selected_candidate: str | None
    attempted_count: int
    method_counts: tuple[tuple[str, int], ...]
    closest: tuple[ProbeFact, ...]
    slowest: ProbeFact | None
    first_invalid: ProbeFact | None
    legacy_fragments_avoided: int


@dataclass(frozen=True)
class DiagnosticEntry:
    entry_id: int
    at_second: int
    kind: str
    summary: str
    protected: bool = False


@dataclass(frozen=True)
class FrameRef:
    ref: str
    role: str
    sensitivity: str = "S2"
    retention: str = "weak/expires"


@dataclass(frozen=True)
class FrameGroup:
    group_ref: str
    frames: tuple[FrameRef, ...]


@dataclass(frozen=True)
class Incident:
    incident_ref: str
    chain: tuple[DiagnosticEntry, ...]
    frame_group_ref: str | None
    ordinary_entries_evicted: int


@dataclass(frozen=True)
class AuthorityRecord:
    event_seq: int
    event_name: str
    level: str
    message: str
    attempts_count: int = 1
    attempted_candidates: int = 0
    legacy_fragments_avoided: int = 0
    incident_ref: str | None = None
    frame_group_ref: str | None = None


@dataclass(frozen=True)
class DomainAggregate:
    domain: str
    operations: int = 0
    candidate_probes: int = 0
    succeeded: int = 0
    failed_attempts: int = 0
    legacy_fragments_avoided: int = 0
    duration_total_ms: int = 0
    duration_max_ms: int = 0


@dataclass(frozen=True)
class PrototypeState:
    scenario: str
    current_scene: str = "INDEX"
    now_second: int = 0
    probe_facts_seen: int = 0
    legacy_fragments_avoided: int = 0
    authority: tuple[AuthorityRecord, ...] = ()
    aggregate: tuple[DomainAggregate, ...] = ()
    last_attempt: AttemptSummary | None = None
    anchors: tuple[DiagnosticEntry, ...] = ()
    tail: tuple[DiagnosticEntry, ...] = ()
    display_tail_budget: int = 12
    ordinary_entries_evicted: int = 0
    incidents: tuple[Incident, ...] = ()
    pre_frames: tuple[int, ...] = ()
    overwritten_frames: int = 0
    frame_groups: tuple[FrameGroup, ...] = ()
    next_entry_id: int = 1
    next_event_seq: int = 1
    next_incident_id: int = 1
    next_frame_id: int = 1
    first_window_done: bool = False
    last_action: str = "prototype started"
    retained: tuple[str, ...] = ()
    discarded: tuple[str, ...] = ()


def new_state(scenario: str = "empty") -> PrototypeState:
    return PrototypeState(scenario=scenario)


def _summarize_attempt(
    facts: tuple[ProbeFact, ...], attempt: int, outcome: str
) -> AttemptSummary:
    methods: dict[str, int] = {}
    for fact in facts:
        methods[fact.method] = methods.get(fact.method, 0) + 1
    selected = next((fact.candidate for fact in facts if fact.matched), None)
    closest = tuple(sorted(facts, key=lambda fact: fact.margin)[:3])
    slowest = max(facts, key=lambda fact: fact.duration_ms, default=None)
    first_invalid = next(
        (fact for fact in facts if fact.reason not in {"matched", "not_matched"}),
        None,
    )
    return AttemptSummary(
        attempt=attempt,
        outcome=outcome,
        selected_candidate=selected,
        attempted_count=len(facts),
        method_counts=tuple(sorted(methods.items())),
        closest=closest,
        slowest=slowest,
        first_invalid=first_invalid,
        legacy_fragments_avoided=sum(
            fact.modeled_legacy_fragments for fact in facts
        ),
    )


def _add_entry(
    state: PrototypeState, kind: str, summary: str, *, protected: bool = False
) -> PrototypeState:
    entry = DiagnosticEntry(
        entry_id=state.next_entry_id,
        at_second=state.now_second,
        kind=kind,
        summary=summary,
        protected=protected,
    )
    if protected:
        anchors = tuple(item for item in state.anchors if item.kind != kind) + (entry,)
        return replace(
            state,
            anchors=anchors,
            next_entry_id=state.next_entry_id + 1,
        )
    tail = state.tail + (entry,)
    evicted = state.ordinary_entries_evicted
    if len(tail) > state.display_tail_budget:
        evicted += len(tail) - state.display_tail_budget
        tail = tail[-state.display_tail_budget :]
    return replace(
        state,
        tail=tail,
        ordinary_entries_evicted=evicted,
        next_entry_id=state.next_entry_id + 1,
    )


def _add_authority(
    state: PrototypeState,
    event_name: str,
    level: str,
    message: str,
    *,
    attempts_count: int = 1,
    attempted_candidates: int = 0,
    legacy_fragments_avoided: int = 0,
    incident_ref: str | None = None,
    frame_group_ref: str | None = None,
) -> PrototypeState:
    record = AuthorityRecord(
        event_seq=state.next_event_seq,
        event_name=event_name,
        level=level,
        message=message,
        attempts_count=attempts_count,
        attempted_candidates=attempted_candidates,
        legacy_fragments_avoided=legacy_fragments_avoided,
        incident_ref=incident_ref,
        frame_group_ref=frame_group_ref,
    )
    return replace(
        state,
        authority=state.authority + (record,),
        next_event_seq=state.next_event_seq + 1,
    )


def _add_aggregate(
    state: PrototypeState,
    domain: str,
    summary: AttemptSummary,
    duration_ms: int,
) -> PrototypeState:
    values = list(state.aggregate)
    index = next(
        (i for i, value in enumerate(values) if value.domain == domain), None
    )
    if index is None:
        values.append(DomainAggregate(domain=domain))
        index = len(values) - 1
    current = values[index]
    values[index] = replace(
        current,
        operations=current.operations + 1,
        candidate_probes=current.candidate_probes + summary.attempted_count,
        succeeded=current.succeeded + int(summary.outcome == "succeeded"),
        failed_attempts=current.failed_attempts
        + int(summary.outcome == "attempt_failed"),
        legacy_fragments_avoided=current.legacy_fragments_avoided
        + summary.legacy_fragments_avoided,
        duration_total_ms=current.duration_total_ms + duration_ms,
        duration_max_ms=max(current.duration_max_ms, duration_ms),
    )
    return replace(state, aggregate=tuple(values))


def observe_scan_attempt(
    state: PrototypeState,
    facts: tuple[ProbeFact, ...],
    *,
    attempt: int,
    result_scene: str | None,
) -> PrototypeState:
    outcome = "succeeded" if result_scene is not None else "attempt_failed"
    summary = _summarize_attempt(facts, attempt, outcome)
    duration_ms = sum(fact.duration_ms for fact in facts)
    state = replace(
        state,
        now_second=state.now_second + max(1, duration_ms // 1000),
        probe_facts_seen=state.probe_facts_seen + len(facts),
        legacy_fragments_avoided=state.legacy_fragments_avoided
        + summary.legacy_fragments_avoided,
        last_attempt=summary,
    )
    state = _add_aggregate(state, "recognition", summary, duration_ms)
    state = _add_entry(
        state,
        "scan_tail",
        f"attempt={attempt} outcome={outcome} candidates={len(facts)} "
        f"closest={[fact.candidate for fact in summary.closest]}",
    )
    if result_scene is not None and result_scene != state.current_scene:
        previous = state.current_scene
        state = _add_entry(
            state,
            "scene_anchor",
            f"scene {previous} -> {result_scene}",
            protected=True,
        )
        state = _add_authority(
            state,
            "recognition.scene.changed",
            "INFO",
            f"scene changed: {previous} -> {result_scene}",
            attempted_candidates=len(facts),
            legacy_fragments_avoided=summary.legacy_fragments_avoided,
        )
        return replace(
            state,
            current_scene=result_scene,
            last_action=f"scan changed scene from {previous} to {result_scene}",
            retained=("one state-change INFO", "bounded attempt representatives"),
            discarded=(
                f"{summary.legacy_fragments_avoided} modeled low-level fragments",
            ),
        )
    return replace(
        state,
        last_action=f"scan attempt {attempt} ended as {outcome}",
        retained=("aggregate counters", "bounded attempt representatives"),
        discarded=(
            "routine authority record",
            f"{summary.legacy_fragments_avoided} modeled low-level fragments",
        ),
    )


def add_control_anchor(state: PrototypeState, operation: str) -> PrototypeState:
    state = replace(state, now_second=state.now_second + 1)
    return _add_entry(
        state,
        "control_anchor",
        f"last control operation={operation}; raw command/body omitted",
        protected=True,
    )


def recovered(
    state: PrototypeState,
    attempts: tuple[tuple[ProbeFact, ...], ...],
    result_scene: str,
) -> PrototypeState:
    avoided = 0
    candidates = 0
    for number, facts in enumerate(attempts, 1):
        outcome_scene = result_scene if number == len(attempts) else None
        state = observe_scan_attempt(
            state,
            facts,
            attempt=number,
            result_scene=outcome_scene,
        )
        avoided += sum(fact.modeled_legacy_fragments for fact in facts)
        candidates += len(facts)
    state = _add_entry(
        state,
        "retry_anchor",
        f"recovered after {len(attempts) - 1} failed attempts",
        protected=True,
    )
    state = _add_authority(
        state,
        "recognition.scan.recovered",
        "WARNING",
        f"scan recovered on attempt {len(attempts)}",
        attempts_count=len(attempts),
        attempted_candidates=candidates,
        legacy_fragments_avoided=avoided,
    )
    return replace(
        state,
        last_action="retry recovered",
        retained=("one recovery WARNING", "attempt counts and representatives"),
        discarded=(
            f"{len(attempts) - 1} per-attempt authority errors",
            "incident freeze",
        ),
    )


def _make_frame_group(
    state: PrototypeState, post_frames: int
) -> tuple[PrototypeState, FrameGroup]:
    frame_ids = list(state.pre_frames[-2:])
    trigger = state.next_frame_id
    frame_ids.append(trigger)
    next_frame = trigger + 1
    roles = ["pre"] * (len(frame_ids) - 1) + ["trigger"]
    for _ in range(min(post_frames, 2)):
        frame_ids.append(next_frame)
        roles.append("post")
        next_frame += 1
    group_ref = f"artifact://failure-frames/group-{state.next_incident_id:02d}"
    group = FrameGroup(
        group_ref=group_ref,
        frames=tuple(
            FrameRef(
                ref=f"artifact://failure-frames/frame-{frame_id:04d}",
                role=role,
            )
            for frame_id, role in zip(frame_ids, roles)
        ),
    )
    return (
        replace(
            state,
            frame_groups=state.frame_groups + (group,),
            next_frame_id=next_frame,
        ),
        group,
    )


def exhausted(
    state: PrototypeState,
    attempts: tuple[tuple[ProbeFact, ...], ...],
    *,
    with_frames: bool = True,
    post_frames: int = 2,
) -> PrototypeState:
    avoided = 0
    candidates = 0
    for number, facts in enumerate(attempts, 1):
        state = observe_scan_attempt(
            state, facts, attempt=number, result_scene=None
        )
        avoided += sum(fact.modeled_legacy_fragments for fact in facts)
        candidates += len(facts)
    frame_group = None
    if with_frames:
        state, frame_group = _make_frame_group(state, post_frames)
    retry_anchor = DiagnosticEntry(
        entry_id=state.next_entry_id,
        at_second=state.now_second,
        kind="retry_anchor",
        summary=f"retry exhausted after {len(attempts)} attempts",
        protected=True,
    )
    state = replace(
        state,
        anchors=tuple(item for item in state.anchors if item.kind != "retry_anchor")
        + (retry_anchor,),
        next_entry_id=state.next_entry_id + 1,
    )
    incident_ref = f"incident://run/task/failure-{state.next_incident_id:02d}"
    chain = tuple(sorted(state.anchors + state.tail, key=lambda item: item.entry_id))
    incident = Incident(
        incident_ref=incident_ref,
        chain=chain,
        frame_group_ref=frame_group.group_ref if frame_group else None,
        ordinary_entries_evicted=state.ordinary_entries_evicted,
    )
    state = replace(
        state,
        incidents=state.incidents + (incident,),
        next_incident_id=state.next_incident_id + 1,
    )
    state = _add_authority(
        state,
        "recognition.scan.failed",
        "ERROR",
        f"scan retry exhausted after {len(attempts)} attempts",
        attempts_count=len(attempts),
        attempted_candidates=candidates,
        legacy_fragments_avoided=avoided,
        incident_ref=incident_ref,
        frame_group_ref=frame_group.group_ref if frame_group else None,
    )
    return replace(
        state,
        last_action="retry exhausted",
        retained=(
            "one final ERROR",
            f"frozen semantic chain with {len(chain)} entries",
            f"{len(frame_group.frames) if frame_group else 0} weak frame references",
        ),
        discarded=(
            f"{len(attempts)} per-attempt authority errors",
            f"{avoided} modeled low-level fragments",
            "raw screenshot bytes from LogEvent",
        ),
    )


def capture_routine_frame(state: PrototypeState) -> PrototypeState:
    frames = state.pre_frames + (state.next_frame_id,)
    overwritten = state.overwritten_frames
    if len(frames) > 2:
        overwritten += len(frames) - 2
        frames = frames[-2:]
    return replace(
        state,
        pre_frames=frames,
        overwritten_frames=overwritten,
        next_frame_id=state.next_frame_id + 1,
    )


def flush_window(state: PrototypeState) -> PrototypeState:
    summary_count = 0
    for aggregate in state.aggregate:
        state = _add_authority(
            state,
            f"{aggregate.domain}.activity.summary",
            "INFO",
            f"{aggregate.operations} operations / {aggregate.candidate_probes} probes",
            attempted_candidates=aggregate.candidate_probes,
            legacy_fragments_avoided=aggregate.legacy_fragments_avoided,
        )
        summary_count += 1
    return replace(
        state,
        now_second=state.now_second + (300 if not state.first_window_done else 900),
        aggregate=(),
        first_window_done=True,
        last_action=f"flushed {summary_count} bounded domain summaries",
        retained=(f"{summary_count} domain summary record(s)",),
        discarded=("all per-probe fragments", "completed aggregate bucket"),
    )


def sample_facts(
    count: int,
    *,
    matched_at: int | None = None,
    method: Method = "template",
    prefix: str = "candidate",
) -> tuple[ProbeFact, ...]:
    facts = []
    for index in range(count):
        threshold = 0.90
        score = 0.10 + ((index * 37) % 790) / 1000
        matched = matched_at is not None and index == matched_at
        if matched:
            score = 0.94
        facts.append(
            ProbeFact(
                candidate=f"{prefix}-{index + 1:03d}",
                method=method,
                matched=matched,
                score=score,
                threshold=threshold,
                duration_ms=3 + (index * 11) % 29,
                reason="matched" if matched else "not_matched",
            )
        )
    return tuple(facts)


def success_scenario() -> PrototypeState:
    state = new_state("successful scan silence")
    return replace(
        observe_scan_attempt(
            state,
            sample_facts(18, matched_at=12),
            attempt=1,
            result_scene="INDEX",
        ),
        scenario="successful scan silence",
    )


def representative_scenario() -> PrototypeState:
    state = new_state("diagnostic representatives")
    facts = sample_facts(205, method="color", prefix="comparator")
    state = observe_scan_attempt(state, facts, attempt=1, result_scene="INDEX")
    return replace(
        state,
        scenario="diagnostic representatives",
        last_action="evaluated 205 color facts without ordinal sampling",
        retained=("three closest-to-threshold facts", "single slowest fact"),
        discarded=("205 per-call records", "remaining raw fact details"),
    )


def window_scenario() -> PrototypeState:
    state = new_state("window aggregation")
    for _ in range(50):
        state = observe_scan_attempt(
            state,
            sample_facts(24, matched_at=20),
            attempt=1,
            result_scene="INDEX",
        )
    screenshot_summary = _summarize_attempt(
        sample_facts(300, method="screenshot", prefix="frame"), 1, "succeeded"
    )
    state = replace(
        state,
        probe_facts_seen=state.probe_facts_seen + 300,
        legacy_fragments_avoided=state.legacy_fragments_avoided
        + screenshot_summary.legacy_fragments_avoided,
    )
    state = _add_aggregate(state, "device", screenshot_summary, 7200)
    return replace(flush_window(state), scenario="window aggregation")


def state_scenario() -> PrototypeState:
    state = new_state("state change")
    for _ in range(10):
        state = observe_scan_attempt(
            state,
            sample_facts(12, matched_at=6),
            attempt=1,
            result_scene="INDEX",
        )
    state = observe_scan_attempt(
        state,
        sample_facts(16, matched_at=14),
        attempt=1,
        result_scene="INFRA_MAIN",
    )
    return replace(state, scenario="state change")


def recovered_scenario() -> PrototypeState:
    attempts = (
        sample_facts(20),
        sample_facts(20),
        sample_facts(15, matched_at=11),
    )
    return replace(
        recovered(new_state("retry recovered"), attempts, "INDEX"),
        scenario="retry recovered",
    )


def exhausted_scenario() -> PrototypeState:
    state = new_state("retry exhausted")
    state = _add_entry(
        state, "scene_anchor", "scene INDEX", protected=True
    )
    state = add_control_anchor(state, "tap:confirm")
    for _ in range(3):
        state = capture_routine_frame(state)
    attempts = (sample_facts(20), sample_facts(20), sample_facts(20))
    return replace(exhausted(state, attempts), scenario="retry exhausted")


def anchors_scenario() -> PrototypeState:
    state = new_state("protected causal anchors")
    state = _add_entry(
        state, "scene_anchor", "scene INDEX -> INFRA_MAIN", protected=True
    )
    state = add_control_anchor(state, "task-step:open-room")
    for index in range(80):
        state = replace(state, now_second=state.now_second + 1)
        state = _add_entry(
            state,
            "scan_tail",
            f"coalesced scan summary {index + 1}",
        )
    attempts = (sample_facts(8), sample_facts(8), sample_facts(8))
    state = exhausted(state, attempts, with_frames=False)
    return replace(state, scenario="protected causal anchors")


def frames_scenario() -> PrototypeState:
    state = new_state("failure screenshot references")
    for _ in range(4):
        state = capture_routine_frame(state)
    attempts = (sample_facts(6), sample_facts(6), sample_facts(6))
    state = exhausted(state, attempts, post_frames=2)
    return replace(state, scenario="failure screenshot references")


SCENARIOS = {
    "success": success_scenario,
    "representatives": representative_scenario,
    "window": window_scenario,
    "state": state_scenario,
    "recovered": recovered_scenario,
    "exhausted": exhausted_scenario,
    "anchors": anchors_scenario,
    "frames": frames_scenario,
}
