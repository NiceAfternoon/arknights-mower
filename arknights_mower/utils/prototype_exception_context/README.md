# THROWAWAY — Wayfinder exception-context prototype

Do not merge this directory. It exists only to resolve the decision ticket
“增强全局异常捕获与关联上下文”. It does not modify the production logging or
exception chain.

## Question answered

Can Flask requests, WebSocket messages, daemon tasks, background threads and
desktop child processes carry one immutable run/request/task context while an
exception crosses several catch sites, retries, recovery and terminal hooks —
without producing duplicate authoritative error records?

The prototype deliberately separates three identities:

- `failure_id` follows one thrown exception occurrence across catch/rethrow
  sites and prevents the same occurrence being finalized twice.
- `fingerprint` groups similar occurrences for retry counts and diagnosis. It
  never suppresses a distinct failure by itself.
- `(run_id, event_seq)` identifies the single immutable authority event and all
  of its file, terminal, WebUI and notification projections.

## HITL verdict

The user accepted the core behavior on 2026-08-11: retry attempts do not emit
repeated ERROR records; successful recovery emits one WARNING summary, and an
exhausted operation emits one final ERROR summary. The same ownership rule is
used by the request, WebSocket, thread and process terminal adapters below.

## Run it

Interactive:

```powershell
python -m arknights_mower.utils.prototype_exception_context.tui
```

Deterministic review of all scenarios:

```powershell
python -m arknights_mower.utils.prototype_exception_context.tui --scenario review
```

The four scenarios show a terminal task failure seen by several boundaries, a
recovered retry group, an explicitly carried desktop child-process context,
and a logging-writer crash that cannot report through its own failed queue.

## Proposed context contract

- Process bootstrap creates `run_id` once for a cold Mower run and passes a
  small serialized carrier explicitly to child-process targets. It does not
  rely on fork inheritance or ambient globals.
- HTTP ingress creates one `request_id` per request. A WebSocket adapter creates
  one per inbound command/message rather than treating a long-lived connection
  as one request.
- The task dispatcher creates or adopts `task_id`, preserving the triggering
  `request_id`; task retries keep the same `task_id`.
- Python thread targets run under an explicitly copied `contextvars` context.
  Raw `Thread(...)` becomes an implementation detail behind the adapter.
- Event construction snapshots IDs before enqueue. The background logging
  thread projects that immutable event and never tries to recover correlation
  from its own ambient context.

## Proposed failure ownership

Helpers and adapters may enrich a failure occurrence but do not log-and-raise.
The closest module that can decide retry/recovery owns the recovery summary. If
the failure escapes, the named terminal execution adapter owns the final event:

| Execution seam | Authority when an exception escapes |
| --- | --- |
| Flask request | request adapter; sanitized response, one `web.request.failed` |
| WebSocket message | per-message adapter; decide continue/close, never echo raw exception |
| Scheduler task | task runner; one recovered WARNING or terminal ERROR |
| Background thread | named thread adapter, with `threading.excepthook` only as last resort |
| Desktop child process | process bootstrap wrapper using the explicit run carrier |
| Logging writer | runtime-owned supervisor using a minimal direct emergency sink |
| Main desktop process | process bootstrap / `sys.excepthook` last resort |

`SystemExit`, `KeyboardInterrupt` and expected Mower cancellation follow normal
lifecycle handling rather than this fault path.

## Standard final-failure shape

The authority event uses the already-decided fixed schema groups:

- bounded, allow-listed `input` and `state` snapshots;
- stable `error.code`, sanitized exception type/message and one relative-path
  cause chain for unexpected failures;
- `recovery` result, failure/attempt counts and final `impact`;
- catalog-backed `advice.code` only when the known cause admits a user action;
  lack of advice is independent of explicit `cause_unknown`;
- `duration_ms`, an optional final-boundary `process_rss_bytes` snapshot, and
  `failure_count`/`attempts_count` from injected clock, metrics and retry
  adapters. Every numeric value printed by this prototype is synthetic input,
  not a measurement of the production runtime.

No locals, arbitrary arguments, request bodies, object `repr`, credentials,
feedback text or LLM content enter the event. The same processed immutable
event is projected everywhere.

## Highest-leverage implementation seam

Keep one deep `FailureContextRuntime` interface shared by execution adapters:

```text
adopt_context(carrier) -> scope
snapshot_for_child(kind) -> carrier
observe_failure(exception, boundary, facts) -> failure_id
finish_failure(failure_id, outcome, impact, metrics) -> CaptureDecision
```

`CaptureDecision` either returns the one processed authority event or a
duplicate/no-authority decision. Callers and tests cross this same seam; clock,
ID source, schema/privacy processor, metrics probe and emergency sink are
injected adapters.

## Evidence boundary

This state prototype validates the identity, propagation and ownership model:
the terminal and recovered scenarios each produce exactly one authority event,
rethrows are suppressed by `failure_id`, distinct retries with the same
fingerprint remain counted, process hops retain IDs, and the writer failure
uses a direct emergency projection.

It does **not** validate queue capacity/backpressure, queue latency, shutdown
flush completeness, a writer crash under real I/O, or CPU/RSS overhead. Those
were selected architecturally by “建立统一日志运行时与兼容适配层” but have no
runnable prototype evidence and must remain an explicit follow-up validation
before the final implementation plan claims those properties.

The file-native incident lifecycle, time-range query compatibility and fixed
prototype evidence remain in “实现有界轮转压缩与按时间检索兼容” at commit
`fbb1c8b43cb06a641d24718ce7969ed6fccad746`; this prototype does not replace or
re-validate that storage decision.
