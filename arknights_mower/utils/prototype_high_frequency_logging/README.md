# THROWAWAY — high-frequency logging policy prototype

Do not merge this directory. It exists only to resolve the Wayfinder decision
ticket “重构视觉识别与设备链路的高频日志”. It does not modify production
recognition, device, logging, storage, or screenshot code.

## Question being prototyped

Can one bounded policy make routine color comparison, resource lookup,
template/feature matching, screenshot capture, input actions, and ADB commands
quiet in production while still making the final failure replayable? The
prototype makes every retention boundary visible: the authority log,
aggregation counters, sampled diagnostic ring, frozen incident chain, and
failure-frame weak references.

## Run it

Interactive review:

```powershell
python -m arknights_mower.utils.prototype_high_frequency_logging.tui
```

Print all eight deterministic review cases:

```powershell
python -m arknights_mower.utils.prototype_high_frequency_logging.tui --scenario review
```

Print one case with `--scenario success`, `sampling`, `window`, `state`,
`recovered`, `exhausted`, `ring`, or `frames`.

## Decision draft exposed by the prototype

### Routine event policy

Every raw call updates a bounded counter before any LogEvent is created.
Routine success never writes one authority record per call in production.

| Family | Production authority log | Diagnostic-ring sampling | Aggregate key |
| --- | --- | --- | --- |
| color comparison | per-call success silent | first + every 100th | registered comparator |
| resource lookup/load | per-call success silent | first + every 100th | resource family, not path |
| template/feature match | per-call result silent | first + every 100th | algorithm + registered resource |
| screenshot capture | per-frame success silent | first + every 20th | backend |
| tap/swipe/key input | per-action success silent | every action | operation kind, not free text |
| ADB command | per-command success silent | every action | command class, never raw command |

Sampling only creates a small, already-sanitized breadcrumb in memory. It does
not create an authority-file record. Development may project the full bounded
diagnostic event, but event names, fields, sensitivity, and outcome do not
change between modes.

The first active aggregate window is five minutes; later windows are fifteen
minutes. A window writes at most one `recognition.activity.summary` and one
`device.activity.summary`, each with at most ten displayed groups. The runtime
tracks at most 256 low-cardinality keys; overflow is counted under `other`,
never retained as an unbounded label. Summaries retain counts, outcome counts,
duration distribution inputs, sampled count, and suppressed-detail count.

The numbers 100, 20, 256, 30 seconds, and 64 diagnostic entries are the policy
candidate being reviewed here, not production measurements. “验证日志运行时背压、故障旁路与关闭语义” owns runnable evidence for the queue and ring memory
bound, CPU/RSS cost, sink failure, and shutdown behavior. If its measurements
require a smaller capacity, implementation must preserve the semantic rules
(most-recent causal tail, explicit eviction count, and no unbounded labels).

### Immediate boundaries

- Re-observing the same scene is silent and counted. A real `from -> to` scene
  change writes one immediate INFO event; it never waits for a window.
- Individual retry failures remain diagnostic breadcrumbs. Recovery writes one
  WARNING summary. Exhaustion writes one authoritative ERROR.
- Recovery does not freeze an incident or frames. The active ring continues and
  its old entries expire normally.
- Exhaustion freezes the already-sanitized causal tail into one incident
  capsule and links it from the ERROR. Breadcrumbs in the capsule are not
  counted as additional authority-file records.

### Diagnostic and screenshot retention

The candidate diagnostic ring keeps the most recent 30 seconds and at most 64
entries per active task; entries older than either boundary are evicted with an
explicit count. Final failure copies the surviving chronological tail into a
file-native incident reference compatible with the fixed storage decision at
commit `fbb1c8b43cb06a641d24718ce7969ed6fccad746`.

Screenshot bytes never enter a LogEvent or the diagnostic ring. The in-memory
frame buffer overwrites routine successes. A final visual/device failure
creates one frame group containing the preceding two frames, trigger frame,
and at most two following frames (no more than five). If the flow has stopped,
missing following frames are not fabricated. The ERROR contains a controlled
group `artifact_ref`; the manifest contains bounded per-frame weak references,
type, sensitivity, reason, size/hash placeholders, and retention state. A
missing or expired artifact is displayed as expired, not as log corruption.
The existing privacy decision still limits a task/error to the most recent 20
deduplicated groups and forbids S3 data.

### Failure ownership and storage references

Retry recovery/exhaustion and the single authority event follow the fixed
exception-context decision and prototype at commit
`b538b75209c4488cebd03a52944684441373025b`. Incident lifecycle, fidelity, and
time-range lookup follow the fixed storage decision and prototype at commit
`fbb1c8b43cb06a641d24718ce7969ed6fccad746`.

The selected unified runtime is treated only as architecture. This prototype
does not prove queue capacity/backpressure, writer-failure bypass, three-second
shutdown flush, actual I/O, throughput, CPU, or RSS.

## Acceptance mapping for the later implementation

- One routine success: zero authority records; one aggregate count; zero or one
  ephemeral sampled breadcrumb according to the table.
- 205 repeated color comparisons: zero authority records; 205 aggregate
  observations; breadcrumbs for ordinal 1, 100, and 200 only.
- A completed mixed window: no per-call records and at most two domain summary
  records, with `raw = summarized + pending` and explicit suppressed/sample
  counts.
- Ten identical scene observations followed by a new scene: exactly one
  immediate state-change INFO.
- Two failures followed by success: exactly one recovery WARNING, no ERROR,
  incident, or persisted frame group.
- Three exhausted attempts: exactly one final ERROR, one incident reference,
  one chronological bounded diagnostic chain, and at most one five-frame group.

These scenario assertions supplement, but do not replace, the established
three independent two-hour windows, median raw-byte and logical-record
reductions both at least 50%, CPU/RSS limits, fault matrix, privacy canaries,
and compatibility checks.
