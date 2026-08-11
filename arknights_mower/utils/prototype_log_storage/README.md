# THROWAWAY — Wayfinder log-lifecycle prototype

Do not merge this directory. It exists only to resolve the decision ticket
“实现有界轮转压缩与按时间检索兼容”. It does not implement production log
storage.

## Question answered

Can fixed, transparent age/value strategies preserve useful unattended-run
history without a per-instance byte quota, while making irreversible semantic
compaction, historical fidelity and destructive manual cleanup visible?

The validated answer is yes:

- Per-instance size is an observed metric, not a cleanup limit.
- Strategies control when detail becomes structured summaries.
- No user-configured hard limit, soft target or size-alert threshold changes
  retention behavior.
- Only a volume-level low-free-space guard may degrade writes to protect the
  application and operating system from an actually full disk.

## Run it

Interactive:

```powershell
python -m arknights_mower.utils.prototype_log_storage.tui
```

Deterministic 210-day lifecycle and 90-day query:

```powershell
python -m arknights_mower.utils.prototype_log_storage.tui --scenario lifecycle
```

Use `m` to seed history, `p` to change strategy, `s` to query old data, and `c`
then `y` to experience the two-stage destructive cleanup confirmation.

## Evidence and fixed lifecycle

The local legacy baseline contains 169 files and 789.4 MiB raw data. A
read-only gzip level-6 pass produced 122.6 MiB (15.5%); hourly raw p95 was
9.8 MiB and the maximum was 48.5 MiB. This proves immediate lossless
compression is valuable, but it does not predict the redesigned system's
multi-week footprint. Production byte targets must therefore come from later
field observation, not this planning ticket.

Every instance owns its own `@app/<space>/log/` lifecycle. Strategies are
visible presets:

| Strategy | Detailed event target |
| --- | ---: |
| 细节优先 | 7 days |
| 均衡 (default) | 3 days |
| 空间优先 | 1 day |

After detail expires:

- Through day 30: structured 15-minute summaries.
- Day 30 through day 180: structured hourly summaries.
- After day 180: structured daily summaries.
- Full incident capsules live for 30 days, then become error fingerprints and
  structured incident digests. A user can export an important capsule before
  it ages out.

Changing to a more aggressive strategy may compact existing data immediately.
Changing back cannot recreate discarded detail, and the UI must say so before
applying the strategy.

## Summary information fidelity

A daily summary is not one opaque sentence or one total. It retains grouped
rows by stable module, task, event name, outcome and approved low-cardinality
dimensions, including:

- first/last occurrence, counts and duration distribution;
- success, failure, retry and recovery transitions;
- error fingerprints and incident references;
- suppression, aggregation, sampling and disk-byte contribution;
- DEBUG/INFO/WARNING/ERROR/CRITICAL logical event counts, persisted detail
  counts, aggregated counts and dropped counts.

The dashboard may render a one-sentence headline, but the structured grouped
data remains expandable. Time precision becomes coarser with age while the
business dimensions remain queryable.

## File-native layout

Summaries remain transparent files under the instance log directory; no
database and no one-file-per-summary layout is required:

```text
log/
├─ detail/runtime-<range>-<sequence>.jsonl.gz
├─ summary/15m/<day>.jsonl.gz
├─ summary/hour/<month>.jsonl.gz
├─ summary/day/<year>.jsonl.gz
├─ incidents/<incident>.jsonl.gz
└─ catalog.json
```

Each coarsening step writes and verifies the replacement chunk first, updates
`catalog.json` atomically, and only then removes the finer source chunk. A
partial/corrupt conversion keeps its intact source and reports degraded
catalog state.

## Query and feedback compatibility

A new range API returns ordered artifacts plus explicit fidelity for every
covered interval: detail, 15-minute, hourly, daily, incident digest or missing.
It uses UTC first/last event metadata rather than filename substring or mtime.
Naive legacy datetimes are interpreted in the configured local timezone.

Feedback flushes the writer, snapshots the active high-water mark and creates
immutable compressed attachments with a manifest. The existing
`get_log_by_time(target_time, time_range=1) -> list[Path]` remains a wrapper,
so current email attachment code continues to work while callers migrate to an
explicit start/end range.

## User controls

The settings page shows only actual per-instance size beside a single manual
historical-log cleanup action. There is no byte quota or size-alert setting.
Cleanup is destructive and requires two confirmations:

1. Preview exact size, date range, summary chunks and incident capsules that
   will be removed.
2. Confirm again after an explicit irreversible-data-loss warning.

The cleanup closes/snapshots the active segment, removes historical detail,
summaries and capsules for that instance, then starts a fresh active segment.
Settings remain intact.

## Highest-leverage implementation seam

Keep a pure lifecycle planner between the logging runtime and filesystem:

```text
plan_lifecycle(catalog, clock, selected_strategy, action)
    -> ordered file operations + updated catalog + fidelity diagnostics
```

Inject the clock, filesystem adapter, compressor and free-space probe around
it. Future implementation tests can drive boundaries, strategy changes,
crash-safe conversion, historical queries and two-stage cleanup without
sleeping, filling a real disk or starting the application.
