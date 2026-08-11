"""TUI for the THROWAWAY source-owned logging decision prototype."""

import argparse
import os

from .model import SCENARIOS, PrototypeState, new_state

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def render(state: PrototypeState, *, clear: bool = True) -> None:
    if clear:
        _clear()
    print(f"{BOLD}THROWAWAY -- source-owned high-frequency logging{RESET}")
    print(f"{DIM}Scenario:{RESET} {state.scenario}")
    print(
        f"{DIM}Target: >=90% median reduction in both uncompressed bytes and logical records.{RESET}"
    )
    print(
        f"{DIM}Policy model only; queue, writer, flush, CPU, RSS and production capacity remain unverified.{RESET}"
    )

    print(f"\n{BOLD}Ownership rule{RESET}")
    print("low-level find/color/template/feature/screenshot/input/ADB: return facts")
    print("scene/task/retry owner: record final semantic outcome")
    print("same-state success=0; change=INFO; recovered=WARNING; exhausted=ERROR")

    print(f"\n{BOLD}Counts{RESET}")
    print(f"bounded probe facts observed:       {state.probe_facts_seen}")
    print(f"modeled legacy fragments avoided:  {state.legacy_fragments_avoided}")
    print(f"authority-file records:            {len(state.authority)}")
    print(f"pending domain aggregates:         {len(state.aggregate)}")
    print(f"protected causal anchors:          {len(state.anchors)}")
    print(f"ordinary semantic tail:            {len(state.tail)}")
    print(f"ordinary entries evicted (demo):   {state.ordinary_entries_evicted}")
    print(f"frozen incidents:                  {len(state.incidents)}")
    print(f"routine frames overwritten:        {state.overwritten_frames}")
    print(f"failure frame groups:              {len(state.frame_groups)}")

    print(f"\n{BOLD}Last attempt representatives{RESET}")
    attempt = state.last_attempt
    if attempt is None:
        print("- none")
    else:
        print(
            f"attempt={attempt.attempt} outcome={attempt.outcome} "
            f"candidates={attempt.attempted_count} methods={dict(attempt.method_counts)}"
        )
        print(f"selected={attempt.selected_candidate or '-'}")
        print(
            "closest="
            + ", ".join(
                f"{fact.candidate}(margin={fact.margin:.3f})"
                for fact in attempt.closest
            )
        )
        if attempt.slowest:
            print(
                f"slowest={attempt.slowest.candidate}({attempt.slowest.duration_ms}ms)"
            )
        if attempt.first_invalid:
            print(
                f"first_invalid={attempt.first_invalid.candidate}:"
                f"{attempt.first_invalid.reason}"
            )
        print(f"low-level fragments avoided={attempt.legacy_fragments_avoided}")

    print(f"\n{BOLD}Authority log ({len(state.authority)} records){RESET}")
    if not state.authority:
        print("- none")
    for record in state.authority:
        print(
            f"- seq={record.event_seq} {record.level} {record.event_name}; "
            f"attempts={record.attempts_count}, candidates={record.attempted_candidates}, "
            f"avoided={record.legacy_fragments_avoided}"
        )
        print(f"  message: {record.message}")
        if record.incident_ref:
            print(f"  incident_ref: {record.incident_ref}")
        if record.frame_group_ref:
            print(f"  frame_group_ref: {record.frame_group_ref}")

    print(f"\n{BOLD}Protected anchors{RESET}")
    if not state.anchors:
        print("- none")
    for entry in state.anchors:
        print(
            f"- e{entry.entry_id} t={entry.at_second}s {entry.kind}: {entry.summary}"
        )

    print(f"\n{BOLD}Recent semantic tail{RESET}")
    if not state.tail:
        print("- none")
    for entry in state.tail:
        print(
            f"- e{entry.entry_id} t={entry.at_second}s {entry.kind}: {entry.summary}"
        )

    print(f"\n{BOLD}Frozen diagnostic chain{RESET}")
    if not state.incidents:
        print("- none; anchors/tail remain in memory only")
    for incident in state.incidents:
        chain = " -> ".join(f"e{entry.entry_id}" for entry in incident.chain)
        print(
            f"- {incident.incident_ref}: entries={len(incident.chain)}, "
            f"ordinary_evicted={incident.ordinary_entries_evicted}"
        )
        print(f"  chain={chain}")
        print(f"  frame_group_ref={incident.frame_group_ref or '-'}")

    print(f"\n{BOLD}Failure screenshot references{RESET}")
    if not state.frame_groups:
        print("- none; routine frame bytes stay ephemeral")
    for group in state.frame_groups:
        print(f"- {group.group_ref}: frames={len(group.frames)}")
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


def interactive() -> None:
    choices = {
        "1": "success",
        "2": "representatives",
        "3": "window",
        "4": "state",
        "5": "recovered",
        "6": "exhausted",
        "7": "anchors",
        "8": "frames",
    }
    state = new_state()
    while True:
        render(state)
        print(
            f"\n{BOLD}[1]{RESET} success silence  "
            f"{BOLD}[2]{RESET} diagnostic representatives  "
            f"{BOLD}[3]{RESET} window aggregate  {BOLD}[4]{RESET} state change"
        )
        print(
            f"{BOLD}[5]{RESET} retry recovered  {BOLD}[6]{RESET} retry exhausted  "
            f"{BOLD}[7]{RESET} causal anchors  {BOLD}[8]{RESET} screenshot refs  "
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
            print(f"\n{'=' * 24} {name} {'=' * 24}")
            render(build(), clear=False)
        return
    if args.scenario:
        render(SCENARIOS[args.scenario](), clear=False)
        return
    interactive()


if __name__ == "__main__":
    main()
