"""Pure state model for the throwaway exception-context prototype.

Question: can execution contexts cross ingress, task, thread, process, and log-writer
seams while recovery and terminal owners produce one authoritative failure event?
"""

from dataclasses import dataclass, replace
from typing import Optional, Tuple


@dataclass(frozen=True)
class CorrelationContext:
    run_id: str
    request_id: Optional[str] = None
    task_id: Optional[str] = None
    process_name: str = "desktop"
    thread_name: str = "main"
    transfer: str = "bootstrap"


@dataclass(frozen=True)
class Observation:
    failure_id: str
    boundary: str
    role: str


@dataclass(frozen=True)
class FailureCase:
    operation_id: str
    error_code: str
    fingerprint: str
    exception_type: str
    sanitized_message: str
    traceback_summary: str
    input_summary: str
    state_summary: str
    unexpected: bool
    cause_known: bool
    failure_ids: Tuple[str, ...]
    observations: Tuple[Observation, ...] = ()
    recovery_result: str = "pending"
    advice_code: Optional[str] = None
    duration_ms: int = 0
    process_rss_bytes: int = 0
    authority_event_seq: Optional[int] = None
    suppressed_authority_attempts: int = 0


@dataclass(frozen=True)
class AuthorityEvent:
    event_seq: int
    event_name: str
    level: str
    context: CorrelationContext
    failure_ids: Tuple[str, ...]
    fingerprint: str
    owner: str
    error_code: str
    recovery_result: str
    impact: str
    advice_code: Optional[str]
    cause_unknown: bool
    duration_ms: int
    process_rss_bytes: int
    metrics_source: str
    attempts_count: int
    failure_count: int
    traceback_included: bool
    input_summary: str
    state_summary: str
    projections: Tuple[str, ...]
    caused_by_seq: Optional[int] = None


@dataclass(frozen=True)
class PrototypeState:
    scenario: str
    context: CorrelationContext
    failure: Optional[FailureCase] = None
    events: Tuple[AuthorityEvent, ...] = ()
    timeline: Tuple[str, ...] = ()
    next_request: int = 1
    next_task: int = 1
    next_failure: int = 1
    next_event_seq: int = 1


def initial_state(scenario: str = "empty") -> PrototypeState:
    return PrototypeState(
        scenario=scenario,
        context=CorrelationContext(run_id="run-20260811-a1b2"),
        timeline=("bootstrap created run context",),
    )


def _note(state: PrototypeState, message: str) -> PrototypeState:
    return replace(state, timeline=state.timeline + (message,))


def enter_request(state: PrototypeState, channel: str) -> PrototypeState:
    request_id = f"req-{channel}-{state.next_request:02d}"
    context = replace(
        state.context,
        request_id=request_id,
        task_id=None,
        transfer=f"{channel} ingress adapter",
    )
    return replace(
        state,
        context=context,
        next_request=state.next_request + 1,
        timeline=state.timeline + (f"{channel} ingress minted {request_id}",),
    )


def dispatch_task(state: PrototypeState) -> PrototypeState:
    task_id = f"task-{state.next_task:02d}"
    context = replace(
        state.context,
        task_id=task_id,
        transfer="explicit task carrier",
    )
    return replace(
        state,
        context=context,
        next_task=state.next_task + 1,
        timeline=state.timeline + (
            f"task dispatcher preserved {context.request_id} and minted {task_id}",
        ),
    )


def hop_thread(state: PrototypeState, thread_name: str) -> PrototypeState:
    context = replace(
        state.context,
        thread_name=thread_name,
        transfer="copy_context().run(thread target)",
    )
    return replace(
        state,
        context=context,
        timeline=state.timeline
        + (f"thread adapter copied immutable context to {thread_name}",),
    )


def hop_process(state: PrototypeState, process_name: str) -> PrototypeState:
    context = replace(
        state.context,
        process_name=process_name,
        thread_name="main",
        transfer="serialized bootstrap carrier",
    )
    return replace(
        state,
        context=context,
        timeline=state.timeline
        + (f"process bootstrap adopted explicit carrier in {process_name}",),
    )


def begin_failure(
    state: PrototypeState,
    *,
    operation_id: Optional[str] = None,
    error_code: str = "device.connection_lost",
    exception_type: str = "ConnectionError",
    unexpected: bool = True,
    cause_known: bool = True,
    input_summary: str = "{action: reconnect, endpoint: $DATA/device-alias}",
    state_summary: str = "{from: working, to: retrying, reason: transport_lost}",
) -> PrototypeState:
    failure_id = f"fail-{state.next_failure:02d}"
    operation = operation_id or state.context.task_id or state.context.request_id or "run"
    failure = FailureCase(
        operation_id=operation,
        error_code=error_code,
        fingerprint=f"fp:{error_code}:solver.py:347",
        exception_type=exception_type,
        sanitized_message="device transport unavailable",
        traceback_summary="solver.py:347 -> device.py:428 -> transport.py:91",
        input_summary=input_summary,
        state_summary=state_summary,
        unexpected=unexpected,
        cause_known=cause_known,
        failure_ids=(failure_id,),
    )
    return replace(
        state,
        failure=failure,
        next_failure=state.next_failure + 1,
        timeline=state.timeline
        + (f"raised {failure_id}; fingerprint groups retries, not authority",),
    )


def observe(state: PrototypeState, boundary: str, role: str) -> PrototypeState:
    if state.failure is None:
        return _note(state, f"{boundary} saw no active failure")
    current_id = state.failure.failure_ids[-1]
    observation = Observation(current_id, boundary, role)
    failure = replace(
        state.failure,
        observations=state.failure.observations + (observation,),
    )
    return replace(
        state,
        failure=failure,
        timeline=state.timeline
        + (f"{boundary} observed {current_id} as {role}; emitted nothing",),
    )


def retry_same_fingerprint(state: PrototypeState) -> PrototypeState:
    if state.failure is None:
        return _note(state, "retry requested without a failure")
    failure_id = f"fail-{state.next_failure:02d}"
    failure = replace(
        state.failure,
        failure_ids=state.failure.failure_ids + (failure_id,),
        duration_ms=state.failure.duration_ms + 800,
    )
    return replace(
        state,
        failure=failure,
        next_failure=state.next_failure + 1,
        timeline=state.timeline
        + (
            f"retry raised distinct {failure_id} with {failure.fingerprint}; aggregated by operation",
        ),
    )


def finalize(
    state: PrototypeState,
    *,
    owner: str,
    event_name: str,
    level: str,
    recovery_result: str,
    impact: str,
    advice_code: Optional[str],
    emergency: bool = False,
    caused_by_seq: Optional[int] = None,
) -> PrototypeState:
    if state.failure is None:
        return _note(state, f"{owner} tried to finalize without a failure")
    if state.failure.authority_event_seq is not None:
        failure = replace(
            state.failure,
            suppressed_authority_attempts=state.failure.suppressed_authority_attempts + 1,
        )
        return replace(
            state,
            failure=failure,
            timeline=state.timeline
            + (
                f"{owner} suppressed duplicate authority for {failure.failure_ids[-1]}",
            ),
        )

    seq = state.next_event_seq
    projections = (
        ("emergency_stderr",)
        if emergency
        else ("authority_file", "terminal", "webui", "notification_policy")
    )
    event = AuthorityEvent(
        event_seq=seq,
        event_name=event_name,
        level=level,
        context=state.context,
        failure_ids=state.failure.failure_ids,
        fingerprint=state.failure.fingerprint,
        owner=owner,
        error_code=state.failure.error_code,
        recovery_result=recovery_result,
        impact=impact,
        advice_code=advice_code,
        cause_unknown=not state.failure.cause_known,
        duration_ms=max(state.failure.duration_ms, 1350),
        process_rss_bytes=max(state.failure.process_rss_bytes, 187_695_104),
        metrics_source="synthetic injected probe",
        attempts_count=max(len(state.failure.failure_ids), 1),
        failure_count=len(state.failure.failure_ids),
        traceback_included=state.failure.unexpected,
        input_summary=state.failure.input_summary,
        state_summary=state.failure.state_summary,
        projections=projections,
        caused_by_seq=caused_by_seq,
    )
    failure = replace(
        state.failure,
        recovery_result=recovery_result,
        advice_code=advice_code,
        authority_event_seq=seq,
    )
    return replace(
        state,
        failure=failure,
        events=state.events + (event,),
        next_event_seq=seq + 1,
        timeline=state.timeline
        + (f"{owner} claimed authority as event_seq={seq}; projections reuse snapshot",),
    )


def writer_crash(state: PrototypeState) -> PrototypeState:
    caused_by = state.events[-1].event_seq if state.events else None
    writer_context = replace(
        state.context,
        request_id=None,
        task_id=None,
        thread_name="logging-writer",
        transfer="runtime-owned thread context",
    )
    state = replace(state, context=writer_context, failure=None)
    state = begin_failure(
        state,
        operation_id="logging-runtime",
        error_code="logging.writer_failed",
        exception_type="OSError",
        cause_known=False,
        input_summary="{sink: authority_file, event_ref: bounded}",
        state_summary="{from: writing, to: degraded, reason: writer_stopped}",
    )
    return finalize(
        state,
        owner="logging-writer-supervisor",
        event_name="logging.writer.failed",
        level="CRITICAL",
        recovery_result="not_attempted",
        impact="authority_file_degraded",
        advice_code=None,
        emergency=True,
        caused_by_seq=caused_by,
    )


def terminal_scenario() -> PrototypeState:
    state = initial_state("terminal dedup")
    state = enter_request(state, "http")
    state = dispatch_task(state)
    state = hop_thread(state, "mower-daemon")
    state = begin_failure(state)
    state = observe(state, "device-adapter", "observer")
    state = observe(state, "task-runner", "recovery-owner")
    state = retry_same_fingerprint(state)
    state = observe(state, "scheduler-loop", "observer")
    state = finalize(
        state,
        owner="task-runner",
        event_name="scheduler.task.failed",
        level="ERROR",
        recovery_result="exhausted",
        impact="task_failed_run_continues",
        advice_code="check_device_connection",
    )
    return finalize(
        state,
        owner="threading.excepthook",
        event_name="runtime.thread.failed",
        level="ERROR",
        recovery_result="exhausted",
        impact="thread_stopped",
        advice_code=None,
    )


def recovered_scenario() -> PrototypeState:
    state = initial_state("recovered retry")
    state = enter_request(state, "websocket-message")
    state = dispatch_task(state)
    state = hop_thread(state, "mower-daemon")
    state = begin_failure(state)
    state = observe(state, "task-runner", "recovery-owner")
    state = retry_same_fingerprint(state)
    state = observe(state, "task-runner", "recovery-owner")
    state = finalize(
        state,
        owner="task-runner",
        event_name="scheduler.task.recovered",
        level="WARNING",
        recovery_result="succeeded",
        impact="task_continues_degraded_false",
        advice_code=None,
    )
    return finalize(
        state,
        owner="websocket-message-adapter",
        event_name="web.command.failed",
        level="ERROR",
        recovery_result="succeeded",
        impact="none",
        advice_code=None,
    )


def process_scenario() -> PrototypeState:
    state = initial_state("desktop child process")
    state = hop_process(state, "webview")
    state = begin_failure(
        state,
        operation_id="webview-process",
        error_code="desktop.webview_crashed",
        exception_type="RuntimeError",
        cause_known=False,
        input_summary="{process: webview, callback: window_start}",
        state_summary="{from: starting, to: browser_fallback, reason: process_crash}",
    )
    state = observe(state, "window-callback", "observer")
    return finalize(
        state,
        owner="process-bootstrap",
        event_name="desktop.process.failed",
        level="ERROR",
        recovery_result="browser_fallback_started",
        impact="desktop_shell_degraded",
        advice_code=None,
    )


def writer_scenario() -> PrototypeState:
    state = terminal_scenario()
    return replace(writer_crash(state), scenario="logging writer emergency path")


SCENARIOS = {
    "terminal": terminal_scenario,
    "recovered": recovered_scenario,
    "process": process_scenario,
    "writer": writer_scenario,
}
