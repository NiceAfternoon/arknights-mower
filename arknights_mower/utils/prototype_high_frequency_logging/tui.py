"""Tiny TUI for the THROWAWAY high-frequency logging policy prototype."""

from __future__ import annotations

import argparse
import os

from .model import FAMILY_POLICIES, SCENARIOS, PrototypeState, new_state

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _print_policy(state: PrototypeState) -> None:
    policy = state.policy
    print(f"{BOLD}Policy candidate{RESET}")
    sampling = ", ".join(
        f"{name}=1/{item.sample_every}"
        for name, item in FAMILY_POLICIES.items()
    )
    print(f"sampling (first is always kept): {sampling}")
    print(
        f"aggregate windows: first={policy.first_window_seconds // 60}m, "
        f"steady={policy.steady_window_seconds // 60}m; "
        f"keys<={policy.aggregate_key_limit}; displayed groups<={policy.summary_top_groups}"
    )
    print(
        f"diagnostic ring target: last {policy.ring_max_seconds}s and "
        f"<={policy.ring_max_entries} entries (resource evidence belongs to issue 44)"
    )
    print(
        f"failure frames: pre<={policy.frame_pre} + trigger + post<={policy.frame_post}; "
        "artifact refs only"
    )


def render(state: PrototypeState, *, clear: bool = True) -> None:
    if clear:
        _clear()
    print(f"{BOLD}THROWAWAY -- high-frequency logging retention prototype{RESET}")
    print(f"{DIM}Scenario:{RESET} {state.scenario}")
    print(
        f"{DIM}This models policy only; it does not validate queue, writer, flush, CPU, or RSS.{RESET}"
    )
    print()
    _print_policy(state)

    print(f"\n{BOLD}Counts and live state{RESET}")
    print(f"raw candidate calls:             {state.raw_calls}")
    print(f"authority-file records:          {len(state.authority)}")
    print(f"per-call records suppressed:     {state.per_call_records_discarded}")
    print(f"pending aggregate observations:  {sum(x.count for x in state.aggregate)}")
    print(f"aggregate key overflow:          {state.aggregate_overflow_count}")
    print(f"active diagnostic breadcrumbs:   {len(state.ring)}")
    print(f"ring entries evicted:             {state.ring_evicted}")
    print(f"ephemeral pre-frame candidates:  {len(state.pre_frames)}")
    print(f"overwritten frame candidates:    {state.frame_candidates_discarded}")
    print(f"frozen incidents:                {len(state.incidents)}")
    print(f"persisted frame groups:           {len(state.frame_groups)}")

    print(f"\n{BOLD}Authority log ({len(state.authority)} records){RESET}")
    if not state.authority:
        print("- none")
    for item in state.authority:
        print(
            f"- seq={item.event_seq} {item.level} {item.event_name}; "
            f"raw={item.raw_count}, suppressed={item.suppressed_count}, "
            f"sampled={item.sampled_count}"
        )
        print(f"  message: {item.message}")
        if item.incident_ref:
            print(f"  incident_ref: {item.incident_ref}")
        if item.frame_group_ref:
            print(f"  frame_group_ref: {item.frame_group_ref}")
        for group in item.groups:
            print(f"  group: {group}")

    print(f"\n{BOLD}Active diagnostic ring ({len(state.ring)} entries){RESET}")
    if not state.ring:
        print("- none")
    visible_ring = state.ring if len(state.ring) <= 12 else state.ring[:3] + state.ring[-7:]
    for item in visible_ring:
        print(
            f"- b{item.breadcrumb_id} t={item.at_second}s {item.event_name} "
            f"key={item.operation_key} outcome={item.outcome} "
            f"ordinal={item.ordinal} ({item.reason})"
        )
    if len(visible_ring) < len(state.ring):
        print(f"  ... {len(state.ring) - len(visible_ring)} middle entries hidden by TUI only")

    print(f"\n{BOLD}Frozen diagnostic chain{RESET}")
    if not state.incidents:
        print("- none; active ring remains ephemeral")
    for incident in state.incidents:
        ids = [f"b{item.breadcrumb_id}" for item in incident.breadcrumbs]
        shown = ids if len(ids) <= 16 else ids[:5] + ["..."] + ids[-8:]
        print(
            f"- {incident.incident_ref}: entries={len(ids)}, "
            f"evicted_before_freeze={incident.ring_evicted_before_freeze}, "
            f"chain={' -> '.join(shown)}"
        )
        print(f"  frame_group_ref: {incident.frame_group_ref or '-'}")

    print(f"\n{BOLD}Failure screenshot references{RESET}")
    if not state.frame_groups:
        print("- none; routine frame candidates stay in memory and may be overwritten")
    for group in state.frame_groups:
        print(f"- {group.group_ref}: reason={group.reason}; frames={len(group.frames)}")
        for frame in group.frames:
            print(
                f"  {frame.role}: {frame.ref}; sensitivity={frame.sensitivity}; "
                f"retention={frame.retention}"
            )

    print(f"\n{BOLD}Last retention decision{RESET}")
    print(f"action: {state.last_action}")
    print("retained:")
    for item in state.retained or ("nothing",):
        print(f"  + {item}")
    print("discarded / never persisted:")
    for item in state.discarded or ("nothing",):
        print(f"  - {item}")


def run_interactive() -> None:
    state = new_state()
    choices = {
        "1": "success",
        "2": "sampling",
        "3": "window",
        "4": "state",
        "5": "recovered",
        "6": "exhausted",
        "7": "ring",
        "8": "frames",
    }
    while True:
        render(state)
        print(
            f"\n{BOLD}[1]{RESET} success silence  {BOLD}[2]{RESET} repeated sampling  "
            f"{BOLD}[3]{RESET} window aggregation  {BOLD}[4]{RESET} state change"
        )
        print(
            f"{BOLD}[5]{RESET} retry recovered  {BOLD}[6]{RESET} retry exhausted  "
            f"{BOLD}[7]{RESET} ring freeze  {BOLD}[8]{RESET} screenshot refs  "
            f"{BOLD}[r]{RESET} reset  {BOLD}[q]{RESET} quit"
        )
        choice = input("> ").strip().lower()
        if choice == "q":
            return
        if choice == "r":
            state = new_state()
        elif choice in choices:
            state = SCENARIOS[choices[choice]]()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["review", *SCENARIOS])
    args = parser.parse_args()
    if args.scenario == "review":
        for name, build in SCENARIOS.items():
            print(f"\n{'=' * 26} {name} {'=' * 26}")
            render(build(), clear=False)
        return
    if args.scenario:
        render(SCENARIOS[args.scenario](), clear=False)
        return
    run_interactive()


if __name__ == "__main__":
    main()
