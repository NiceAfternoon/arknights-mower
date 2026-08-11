# THROWAWAY — source-owned high-frequency logging prototype

Do not merge this directory. It exists only as primary-source evidence for the
Wayfinder decision ticket “重构视觉识别与设备链路的高频日志”. It does not
modify production recognition, device, logging, storage, or screenshot code.

## Question answered

Can the code that knows the final operation outcome own logging, while
`find()`, color comparison, template/feature matching, screenshot transport,
input, and ADB primitives return bounded facts without producing routine log
fragments?

The HITL answer is yes. The original fixed `1/100`, `1/20`, and plain
“30 seconds / 64 entries” proposal was rejected after user review and a
read-only audit of the existing logs. The validated direction is source-owned
success silence, semantic aggregation, protected causal anchors, one recovery
WARNING, and one exhaustion ERROR.

## Run it

Interactive:

```powershell
python -m arknights_mower.utils.prototype_high_frequency_logging.tui
```

All deterministic review cases:

```powershell
python -m arknights_mower.utils.prototype_high_frequency_logging.tui --scenario review
```

Individual cases: `success`, `representatives`, `window`, `state`, `recovered`,
`exhausted`, `anchors`, and `frames`.

## Read-only evidence from the current logs

The audit scanned 169 files. It parsed 5,483,864 timestamped records from
821,470,428 bytes; 5,357,571 records were DEBUG.

Recognition/device families accounted for approximately 90.3% of records and
81.2% of parsed bytes. The largest call sites included:

- `Recognizer.find`: 1,813,636 records / 174,677,912 bytes;
- `cmatch`: 1,039,177 / 211,139,003;
- template-result logging in `Recognizer.find`: 342,952 / 42,249,736;
- transformation-matrix logging in `Matcher.score`: 273,918 / 58,954,432;
- screenshot save/capture fragments: more than 430,000 records;
- device input fragments: 174,576 records;
- ADB fragments: 85,029 records.

The same ownership error exists outside recognition: routine dorm lookup,
operator updates and initialization, predicate polling, full scheduler/task
object dumps, SQLite success details, and `logger.exception` inside retry
loops. In particular, `agent_arrange_room` produced 2,378 ERROR records from a
recoverable retry owner, with one exact message repeated up to 677 times.

This historical audit is evidence for prioritization, not the paired
acceptance run. The user raised the desired final outcome to median uncompressed
bytes and logical records both reduced by at least 90% on the established three
independent two-hour workload windows. Compression, queue drops, or disabling
diagnostics cannot count toward that reduction.

## Source ownership decision

The current `get_scene()` family uses an `if/elif` chain to call `find()` for
candidate resources until one matches. `find()` logs before the caller knows
whether the overall scan succeeds, and color/template/feature internals add
more fragments. Logging ownership therefore moves upward:

```text
scene/task owner
  ├─ starts one operation attempt
  ├─ low-level primitives return ProbeFact values without routine logging
  ├─ accumulator keeps bounded counters and diagnostic representatives
  └─ owner records the final semantic outcome
```

Production behavior:

- successful scan with no state change: no authority record;
- real state change: one immediate INFO with `from`, `to`, and reason;
- failed attempts followed by recovery: one WARNING summary;
- retry exhaustion: one ERROR with one frozen incident reference;
- screenshot/input/ADB routine success: silent and aggregated at the operation
  owner, never logged as raw command text, path, response, coordinates list, or
  image bytes.

The compatibility interface may keep returning the existing scope/boolean to
callers. Internally, a pure `ProbeFact` records registered candidate key,
algorithm, outcome, bounded score/threshold margin, duration, and stable reason.
The operation accumulator retains at most:

- the three closest-to-threshold candidate facts;
- the single slowest fact;
- the first invalid/missing-resource fact;
- the selected match, when present.

Duplicates share one representative slot. There is no ordinal sampling and no
unbounded fact list.

## Aggregation and diagnostic chain

High-frequency production summaries retain the already-decided first
five-minute window and later fifteen-minute windows. Each active window emits
at most one recognition-domain and one device-domain summary with counts,
method/outcome groups, latency distribution, suppressed-fragment estimate, and
overflow count. State changes, degradation, recovery, exhaustion, and close
flush immediately; they do not wait for the window.

The diagnostic buffer stores semantic entries, not raw `find()` fragments:

- protected anchors: last state change, current task step, last control action
  before the resulting observation, and retry boundaries;
- a coalesced recent tail of scan/action summaries;
- bounded representative probe facts inside each summary.

Ordinary tail entries may be evicted, but the causal anchors required to
explain the active operation survive a simple age cutoff. Final failure freezes
anchors plus the surviving tail in chronological order. The actual byte/entry
capacity, queue interaction, and CPU/RSS proof remain owned by “验证日志运行时背压、故障旁路与关闭语义”; this prototype deliberately uses a tiny display budget and does not claim a production capacity.

Screenshot bytes remain outside LogEvent. A final visual/device failure links
one weak frame group containing the preceding two frames, trigger frame, and at
most two following frames. Stopped flows do not fabricate following frames.
The privacy decision's S2 metadata, no-S3 rule, deduplication, twenty-group
limit, expiry, preview, and opt-out contract continue unchanged.

## Fixed decision dependencies and evidence boundary

- Event identity, levels, success silence, retry recovery/exhaustion, and one
  authority error follow “定义稳定的日志事件模型与等级语义”.
- Bounded fields, failure frames, and `artifact_ref` follow “定义日志敏感数据分级与脱敏策略”.
- Incident lifecycle and range-query compatibility follow “实现有界轮转压缩与按时间检索兼容” and fixed prototype commit
  `fbb1c8b43cb06a641d24718ce7969ed6fccad746`.
- Failure ownership follows “增强全局异常捕获与关联上下文” and fixed
  prototype commit `b538b75209c4488cebd03a52944684441373025b`.

The selected unified runtime remains architecture only. This prototype does
not validate queue capacity/backpressure, writer failure bypass, shutdown
flush, actual I/O, throughput, CPU, or RSS. It also does not claim that this
ticket alone achieves the new global dual-90% target; the audit shows that long
object dumps and retry errors outside recognition/device must also be reviewed.
