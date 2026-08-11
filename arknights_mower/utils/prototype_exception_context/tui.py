"""Tiny TUI for driving the throwaway exception-context state model."""

import argparse
import json
import os

from .model import SCENARIOS, AuthorityEvent, PrototypeState, initial_state


BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def _event_dict(event: AuthorityEvent) -> dict:
    return {
        "identity": {
            "event_seq": event.event_seq,
            "event_name": event.event_name,
            "level": event.level,
        },
        "correlation": {
            "run_id": event.context.run_id,
            "request_id": event.context.request_id,
            "task_id": event.context.task_id,
            "process": event.context.process_name,
            "thread": event.context.thread_name,
        },
        "error": {
            "failure_ids": event.failure_ids,
            "fingerprint": event.fingerprint,
            "code": event.error_code,
            "traceback_included_once": event.traceback_included,
        },
        "recovery": {
            "result": event.recovery_result,
            "impact": event.impact,
        },
        "advice": {
            "code": event.advice_code,
            "cause_unknown": event.cause_unknown,
        },
        "metrics": {
            "duration_ms": event.duration_ms,
            "process_rss_bytes": event.process_rss_bytes,
            "source": event.metrics_source,
            "attempts_count": event.attempts_count,
            "failure_count": event.failure_count,
        },
        "bounded_facts": {
            "input": event.input_summary,
            "state": event.state_summary,
        },
        "owner": event.owner,
        "projections": event.projections,
        "caused_by_seq": event.caused_by_seq,
    }


def render(state: PrototypeState, *, clear: bool = True) -> None:
    if clear:
        os.system("cls" if os.name == "nt" else "clear")
    context = state.context
    print(f"{BOLD}THROWAWAY — exception context / ownership prototype{RESET}")
    print(f"{DIM}Scenario:{RESET} {state.scenario}")
    print(f"\n{BOLD}Current context{RESET}")
    print(f"run_id:      {context.run_id}")
    print(f"request_id:  {context.request_id or '-'}")
    print(f"task_id:     {context.task_id or '-'}")
    print(f"execution:   {context.process_name}/{context.thread_name}")
    print(f"transfer:    {context.transfer}")

    print(f"\n{BOLD}Failure authority state{RESET}")
    if state.failure is None:
        print("none")
    else:
        failure = state.failure
        print(f"operation:   {failure.operation_id}")
        print(f"failure_ids: {', '.join(failure.failure_ids)}")
        print(f"fingerprint: {failure.fingerprint}")
        print(f"outcome:     {failure.recovery_result}")
        print(f"authority:   {failure.authority_event_seq or '-'}")
        print(f"duplicates:  {failure.suppressed_authority_attempts}")

    print(f"\n{BOLD}Authoritative outputs ({len(state.events)}){RESET}")
    if not state.events:
        print("none")
    for event in state.events:
        print(json.dumps(_event_dict(event), ensure_ascii=False, indent=2))

    print(f"\n{BOLD}Recent transitions{RESET}")
    for item in state.timeline[-8:]:
        print(f"- {item}")


def run_interactive() -> None:
    state = initial_state()
    while True:
        render(state)
        print(
            f"\n{BOLD}[1]{RESET} terminal + duplicate  "
            f"{BOLD}[2]{RESET} recovered retries  "
            f"{BOLD}[3]{RESET} process hop  "
            f"{BOLD}[4]{RESET} writer crash  "
            f"{BOLD}[r]{RESET} reset  {BOLD}[q]{RESET} quit"
        )
        choice = input("> ").strip().lower()
        if choice == "q":
            return
        if choice == "r":
            state = initial_state()
        elif choice in {"1", "2", "3", "4"}:
            key = {"1": "terminal", "2": "recovered", "3": "process", "4": "writer"}[
                choice
            ]
            state = SCENARIOS[key]()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["review", *SCENARIOS])
    args = parser.parse_args()
    if args.scenario == "review":
        for name, build in SCENARIOS.items():
            print(f"\n=== {name} ===")
            render(build(), clear=False)
        return
    if args.scenario:
        render(SCENARIOS[args.scenario](), clear=False)
        return
    run_interactive()


if __name__ == "__main__":
    main()
