"""Interactive shell for the THROWAWAY log-lifecycle prototype."""

from __future__ import annotations

import argparse
import os
from collections import Counter

from .model import (
    PROFILES,
    LifecycleState,
    add_day,
    confirm_manual_cleanup,
    cycle_strategy,
    new_state,
    preview_manual_cleanup,
    query_days_ago,
    seed_history,
    total_stored_mib,
)


BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def render(state: LifecycleState) -> str:
    profile = PROFILES[state.strategy]
    counts = Counter(day.resolution for day in state.days)
    incidents = sum(day.has_incident for day in state.days)
    full_incidents = sum(day.incident_full for day in state.days)
    lines = [
        f"{BOLD}THROWAWAY: age/value log lifecycle{RESET}",
        "No per-instance byte quota. Size is observed; strategy controls fidelity by age.",
        "",
        f"{BOLD}Instance state{RESET}",
        f"strategy={profile.label}  detailed target={profile.detail_days}d",
        "15-minute summaries until day 30; hourly until day 180; daily afterward",
        f"stored size={total_stored_mib(state):.2f} MiB  history={len(state.days)} days",
        f"detail={counts['detail']}d  15m={counts['15m']}d  "
        f"hour={counts['hour']}d  day={counts['day']}d",
        f"incidents={incidents}; full capsules (<30d)={full_incidents}",
        "",
        f"{BOLD}Storage layout{RESET}",
        "detail/*.jsonl.gz; summary/15m/<day>.jsonl.gz;",
        "summary/hour/<month>.jsonl.gz; summary/day/<year>.jsonl.gz; catalog.json",
    ]
    if state.last_query:
        query = state.last_query
        lines.extend(
            [
                "",
                f"{BOLD}Historical query: {query.requested_day:%Y-%m-%d}{RESET}",
                f"fidelity={query.resolution or 'missing'}",
                query.headline,
                *query.level_lines,
            ]
        )
    if state.pending_cleanup:
        preview = state.pending_cleanup
        lines.extend(
            [
                "",
                f"{BOLD}FIRST CONFIRMATION — destructive cleanup preview{RESET}",
                f"delete {preview.days} historical days, {preview.summaries} summary days, "
                f"and {preview.full_incidents} full incident capsules",
                f"reclaim approximately {preview.reclaim_mib:.2f} MiB",
                f"{BOLD}Press [y] for the second confirmation, or any other action to cancel.{RESET}",
            ]
        )
    lines.extend(
        [
            "",
            f"{DIM}Last action: {state.last_action}{RESET}",
            "",
            f"{BOLD}[n]{RESET} normal day  {BOLD}[f]{RESET} noisy/incident day  "
            f"{BOLD}[m]{RESET} seed 210 days",
            f"{BOLD}[s]{RESET} query 90 days ago  {BOLD}[p]{RESET} cycle strategy",
            f"{BOLD}[c]{RESET} preview manual cleanup  {BOLD}[y]{RESET} second confirmation",
            f"{BOLD}[r]{RESET} reset  {BOLD}[q]{RESET} quit",
        ]
    )
    return "\n".join(lines)


def lifecycle_scenario() -> LifecycleState:
    state = seed_history(new_state(), 210)
    return query_days_ago(state, 90)


def interactive() -> None:
    state = new_state()
    while True:
        _clear()
        print(render(state))
        command = input("\ncommand> ").strip().lower()[:1]
        if command == "q":
            return
        if command == "n":
            state = add_day(state)
        elif command == "f":
            state = add_day(state, noisy=True)
        elif command == "m":
            state = seed_history(state, 210)
        elif command == "s":
            state = query_days_ago(state, 90)
        elif command == "p":
            state = cycle_strategy(state)
        elif command == "c":
            state = preview_manual_cleanup(state)
        elif command == "y":
            state = confirm_manual_cleanup(state)
        elif command == "r":
            state = new_state(state.strategy)
        elif state.pending_cleanup:
            state = LifecycleState(
                now=state.now,
                strategy=state.strategy,
                days=state.days,
                last_action="cleanup cancelled",
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        choices=("lifecycle",),
        help="print a deterministic lifecycle scenario instead of opening the TUI",
    )
    args = parser.parse_args()
    if args.scenario == "lifecycle":
        print(render(lifecycle_scenario()))
        return
    interactive()


if __name__ == "__main__":
    main()
