import re
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from typing import Mapping

LEDGER_CATEGORIES = {
    "visual_device_core",
    "visual_intermediate",
    "object_dump",
    "scheduler_state_sqlite",
    "repeated_polling",
    "retry_error_duplication",
}
LEDGER_REQUIRED_FIELDS = (
    "source",
    "function",
    "level",
    "message_shape",
    "target_message_shape",
    "category",
    "consumers",
    "decision",
    "reason",
    "change",
    "bounded_fields",
    "test",
    "selection_basis",
)
LEDGER_NONEMPTY_TEXT_FIELDS = (
    "source",
    "function",
    "level",
    "message_shape",
    "target_message_shape",
    "reason",
    "change",
    "test",
)
TARGET_FIELD_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
UNBOUNDED_TARGET_RE = re.compile(
    r"<(?:object|list)>|(?:repr|str)\s*\(|truncat(?:e|ed|ion)|\*\*",
    re.IGNORECASE,
)
UNBOUNDED_CHANGE_RE = re.compile(
    r"\b(?:dump|repr|truncate|truncated|truncation)\b|\bstr\s*\(",
    re.IGNORECASE,
)
COVERAGE_THRESHOLD = 0.95


@dataclass(frozen=True)
class LogSelector:
    source: str | None
    function: str | None
    level: str | None
    message_shape: str | None

    @classmethod
    def from_mapping(cls, item: Mapping) -> "LogSelector":
        return cls(
            source=item.get("source"),
            function=item.get("function"),
            level=item.get("level"),
            message_shape=item.get("message_shape"),
        )

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "function": self.function,
            "level": self.level,
            "message_shape": self.message_shape,
        }

    def label(self) -> str:
        return "/".join(
            str(value)
            for value in (
                self.source,
                self.function,
                self.level,
                self.message_shape,
            )
        )


def _coverage_for_rows(rows: list[dict], report: dict, window_id: str) -> dict:
    total_records = report.get("totals", {}).get("logical_records", 0)
    total_bytes = report.get("totals", {}).get("actual_file_bytes", 0)
    selected_records = sum(row["windows"][window_id]["count"] for row in rows)
    selected_bytes = sum(row["windows"][window_id]["actual_file_bytes"] for row in rows)
    return {
        "window_id": window_id,
        "record_ratio": selected_records / total_records if total_records else 0.0,
        "byte_ratio": selected_bytes / total_bytes if total_bytes else 0.0,
    }


def _coverage_meets_gate(coverage: dict) -> bool:
    return (
        coverage["record_ratio"] >= COVERAGE_THRESHOLD
        and coverage["byte_ratio"] >= COVERAGE_THRESHOLD
    )


def _reaches_coverage_gate(
    rows: list[dict], reports: list[dict], window_ids: list[str]
) -> bool:
    return all(
        _coverage_meets_gate(coverage)
        for coverage in (
            _coverage_for_rows(rows, report, window_id)
            for report, window_id in zip(reports, window_ids)
        )
    )


def _smallest_residual_set(
    base_rows: list[dict],
    candidate_rows: list[dict],
    reports: list[dict],
    window_ids: list[str],
) -> tuple[dict, ...] | None:
    if _reaches_coverage_gate(base_rows, reports, window_ids):
        return ()

    def pareto_rank(row: dict) -> tuple[float, str]:
        contribution = 0.0
        for report, window_id in zip(reports, window_ids):
            totals = report.get("totals", {})
            values = row["windows"][window_id]
            total_records = totals.get("logical_records", 0)
            total_bytes = totals.get("actual_file_bytes", 0)
            if total_records:
                contribution += values["count"] / total_records
            if total_bytes:
                contribution += values["actual_file_bytes"] / total_bytes
        return (-contribution, repr(LogSelector.from_mapping(row)))

    ordered_candidates = sorted(candidate_rows, key=pareto_rank)
    minimum_candidate_count = 0
    for report, window_id in zip(reports, window_ids):
        totals = report.get("totals", {})
        for value_key, total_key in (
            ("count", "logical_records"),
            ("actual_file_bytes", "actual_file_bytes"),
        ):
            target = COVERAGE_THRESHOLD * totals.get(total_key, 0)
            base_value = sum(row["windows"][window_id][value_key] for row in base_rows)
            deficit = max(0, target - base_value)
            if not deficit:
                continue
            accumulated = 0
            dimension_minimum = 0
            for dimension_minimum, contribution in enumerate(
                sorted(
                    (
                        row["windows"][window_id][value_key]
                        for row in ordered_candidates
                    ),
                    reverse=True,
                ),
                start=1,
            ):
                accumulated += contribution
                if accumulated >= deficit:
                    break
            else:
                return None
            minimum_candidate_count = max(minimum_candidate_count, dimension_minimum)

    for candidate_count in range(
        max(1, minimum_candidate_count), len(ordered_candidates) + 1
    ):
        for selected in combinations(ordered_candidates, candidate_count):
            if _reaches_coverage_gate([*base_rows, *selected], reports, window_ids):
                return selected
    return None


def _validate_windows(reports: list[dict], reasons: list[str]):
    environments = []
    window_ids = []
    window_bounds = []
    report_indexes = []
    for index, report in enumerate(reports):
        window = report.get("window", {})
        window_id = window.get("window_id") or f"window-{index + 1}"
        window_ids.append(window_id)
        environments.append(window.get("environment"))
        if window.get("phase") != "before":
            reasons.append(f"{window_id} must be a before window")
        if report.get("validity", {}).get("valid") is not True:
            reasons.append(f"{window_id} is not a valid representative window")
        try:
            started_at = datetime.fromisoformat(window["started_at"])
            ended_at = datetime.fromisoformat(window["ended_at"])
            if started_at.utcoffset() is None or ended_at.utcoffset() is None:
                raise ValueError
            window_bounds.append((started_at, ended_at))
        except (KeyError, TypeError, ValueError):
            reasons.append(f"{window_id} requires timezone-aware start and end times")
        report_indexes.append(
            {LogSelector.from_mapping(row): row for row in report.get("pareto", [])}
        )

    if len(set(window_ids)) != len(window_ids):
        reasons.append("before windows must have unique window IDs")
    if len(window_bounds) == len(reports):
        ordered_bounds = sorted(window_bounds)
        if any(
            current_start < previous_end
            for (_, previous_end), (current_start, _) in zip(
                ordered_bounds, ordered_bounds[1:]
            )
        ):
            reasons.append("before windows must not overlap")
    if environments and any(item != environments[0] for item in environments[1:]):
        reasons.append("all before windows must use the same environment")
    return window_ids, report_indexes


def _is_finite_field_descriptor(descriptor: object, *, named: bool) -> bool:
    if not isinstance(descriptor, dict):
        return False
    name_keys = {"name"} if named else set()
    if named and (
        not isinstance(descriptor.get("name"), str) or not descriptor["name"].strip()
    ):
        return False

    kind = descriptor.get("kind")
    if kind == "boolean":
        return set(descriptor) == name_keys | {"kind"}
    if kind == "integer":
        if set(descriptor) != name_keys | {"kind", "minimum", "maximum"}:
            return False
        minimum = descriptor.get("minimum")
        maximum = descriptor.get("maximum")
        return (
            isinstance(minimum, int)
            and not isinstance(minimum, bool)
            and isinstance(maximum, int)
            and not isinstance(maximum, bool)
            and minimum <= maximum
        )
    if kind == "string":
        max_length = descriptor.get("max_length")
        return (
            set(descriptor) == name_keys | {"kind", "max_length"}
            and isinstance(max_length, int)
            and not isinstance(max_length, bool)
            and max_length > 0
        )
    if kind == "enum":
        values = descriptor.get("values")
        if set(descriptor) != name_keys | {"kind", "values"}:
            return False
        if not isinstance(values, list) or not values:
            return False
        scalar_types = (str, int, float, bool, type(None))
        return all(isinstance(value, scalar_types) for value in values) and len(
            {(type(value).__name__, repr(value)) for value in values}
        ) == len(values)
    if kind == "list":
        max_items = descriptor.get("max_items")
        return (
            set(descriptor) == name_keys | {"kind", "max_items", "items"}
            and isinstance(max_items, int)
            and not isinstance(max_items, bool)
            and max_items > 0
            and _is_finite_field_descriptor(descriptor.get("items"), named=False)
        )
    return False


def _bounded_field_names(bounded_fields: object) -> tuple[list[str], bool]:
    if not isinstance(bounded_fields, list):
        return [], False
    if not all(
        _is_finite_field_descriptor(descriptor, named=True)
        for descriptor in bounded_fields
    ):
        return [], False
    names = [descriptor["name"] for descriptor in bounded_fields]
    return names, len(set(names)) == len(names)


def _validate_declared_row(declared: dict, row_index: int, reasons: list[str]):
    for field in LEDGER_REQUIRED_FIELDS:
        if field not in declared or declared[field] is None:
            reasons.append(f"ledger row {row_index} requires {field}")
    for field in LEDGER_NONEMPTY_TEXT_FIELDS:
        value = declared.get(field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(
                f"ledger row {row_index} requires non-empty text for {field}"
            )
    if declared.get("category") not in LEDGER_CATEGORIES:
        reasons.append(f"ledger row {row_index} has an unsupported category")
    if declared.get("decision") not in {"include", "exclude"}:
        reasons.append(f"ledger row {row_index} decision must be include or exclude")
    if declared.get("selection_basis") not in {
        "scope_required",
        "scope_consistency",
        "pareto_gap",
    }:
        reasons.append(
            f"ledger row {row_index} selection_basis must be scope_required, "
            "scope_consistency, or pareto_gap"
        )

    consumers = declared.get("consumers")
    if (
        not isinstance(consumers, list)
        or not consumers
        or any(not isinstance(item, str) or not item.strip() for item in consumers)
    ):
        reasons.append(f"ledger row {row_index} requires at least one consumer")

    bounded_fields = declared.get("bounded_fields")
    if not isinstance(bounded_fields, list):
        reasons.append(f"ledger row {row_index} bounded_fields must be a list")
        bounded_fields = []
    bounded_field_names, has_finite_limits = _bounded_field_names(bounded_fields)
    if isinstance(bounded_fields, list) and not has_finite_limits:
        reasons.append(
            f"ledger row {row_index} bounded_fields must define explicit finite limits"
        )

    target_shape = declared.get("target_message_shape")
    if isinstance(target_shape, str) and UNBOUNDED_TARGET_RE.search(target_shape):
        reasons.append(
            f"ledger row {row_index} target_message_shape must not preserve "
            "object dumps or truncation"
        )
    change = declared.get("change")
    if isinstance(change, str) and UNBOUNDED_CHANGE_RE.search(change):
        reasons.append(
            f"ledger row {row_index} change must not dump objects or truncate output"
        )
    if declared.get("decision") == "include":
        if declared.get("change") == "silent":
            if target_shape != "<silent>" or bounded_fields:
                reasons.append(
                    f"ledger row {row_index} silent change must use <silent> "
                    "with no bounded fields"
                )
        elif isinstance(target_shape, str):
            target_fields = TARGET_FIELD_RE.findall(target_shape)
            if not bounded_fields or sorted(target_fields) != sorted(
                bounded_field_names
            ):
                reasons.append(
                    f"ledger row {row_index} target placeholders must exactly match "
                    "bounded_fields"
                )


def _enrich_rows(
    declaration: list[dict],
    window_ids: list[str],
    report_indexes: list[dict],
    reasons: list[str],
) -> list[dict]:
    seen_selectors = set()
    rows = []
    for row_index, declared in enumerate(declaration, start=1):
        _validate_declared_row(declared, row_index, reasons)
        selector = LogSelector.from_mapping(declared)
        if selector in seen_selectors:
            reasons.append(f"ledger row {row_index} duplicates an earlier selector")
        seen_selectors.add(selector)
        windows = {}
        for window_id, report_index in zip(window_ids, report_indexes):
            matched = report_index.get(selector, {})
            windows[window_id] = {
                "count": matched.get("count", 0),
                "actual_file_bytes": matched.get("actual_file_bytes", 0),
            }
        if declared.get("selection_basis") == "pareto_gap" and any(
            not values["count"] for values in windows.values()
        ):
            reasons.append(
                f"ledger row {row_index} is not stable across all before windows"
            )
        rows.append({**declared, "windows": windows})
    return rows


def _stable_residual_rows(
    report_indexes: list[dict],
    window_ids: list[str],
    base_selectors: set[LogSelector],
) -> list[dict]:
    if not report_indexes:
        return []
    stable_selectors = set(report_indexes[0])
    for report_index in report_indexes[1:]:
        stable_selectors.intersection_update(report_index)
    stable_selectors.difference_update(base_selectors)

    rows = []
    for selector in sorted(stable_selectors, key=repr):
        windows = {}
        for window_id, report_index in zip(window_ids, report_indexes):
            matched = report_index[selector]
            windows[window_id] = {
                "count": matched.get("count", 0),
                "actual_file_bytes": matched.get("actual_file_bytes", 0),
            }
        if all(values["count"] for values in windows.values()):
            rows.append({**selector.as_dict(), "windows": windows})
    return rows


def _classify_residual_rows(
    stable_rows: list[dict],
    declared_rows: list[dict],
    out_of_scope_rules: list[dict],
    reasons: list[str],
) -> tuple[list[dict], list[dict]]:
    declared_selectors = {LogSelector.from_mapping(row): row for row in declared_rows}
    compiled_rules = []
    required_rule_fields = {
        "source",
        "function",
        "level",
        "message_shape",
        "reason",
    }
    if not isinstance(out_of_scope_rules, list):
        reasons.append("out_of_scope_rules must be a list")
        out_of_scope_rules = []
    for rule_index, rule in enumerate(out_of_scope_rules, start=1):
        if not isinstance(rule, dict) or set(rule) != required_rule_fields:
            reasons.append(
                f"out_of_scope rule {rule_index} must define only selector patterns "
                "and reason"
            )
            continue
        if not isinstance(rule["reason"], str) or not rule["reason"].strip():
            reasons.append(f"out_of_scope rule {rule_index} requires a reason")
            continue
        try:
            patterns = {
                field: re.compile(rule[field])
                for field in ("source", "function", "level", "message_shape")
            }
        except (TypeError, re.error):
            reasons.append(
                f"out_of_scope rule {rule_index} contains an invalid selector pattern"
            )
            continue
        compiled_rules.append((rule_index, rule, patterns))

    eligible_rows = []
    out_of_scope_rows = []
    for stable_row in stable_rows:
        selector = LogSelector.from_mapping(stable_row)
        if selector in declared_selectors:
            eligible_rows.append(stable_row)
            continue
        matches = []
        selector_values = selector.as_dict()
        for rule_index, rule, patterns in compiled_rules:
            if all(
                patterns[field].fullmatch(str(selector_values[field]))
                for field in patterns
            ):
                matches.append((rule_index, rule))
        if not matches:
            reasons.append(
                f"stable residual selector {selector.label()} requires a ledger row "
                "or out_of_scope rule"
            )
        elif len(matches) > 1:
            reasons.append(
                f"stable residual selector {selector.label()} matches multiple "
                "out_of_scope rules"
            )
        else:
            rule_index, rule = matches[0]
            out_of_scope_rows.append(
                {
                    **selector.as_dict(),
                    "rule_index": rule_index,
                    "reason": rule["reason"],
                }
            )
    return eligible_rows, out_of_scope_rows


def freeze_ledger(
    reports: list[dict],
    declaration: list[dict],
    out_of_scope_rules: list[dict] | None = None,
) -> dict:
    reasons = []
    if len(reports) != 3:
        reasons.append("exactly three before-window reports are required")

    window_ids, report_indexes = _validate_windows(reports, reasons)
    rows = _enrich_rows(declaration, window_ids, report_indexes, reasons)

    coverage = []
    included_rows = [row for row in rows if row.get("decision") == "include"]
    for report, window_id in zip(reports, window_ids):
        window_coverage = _coverage_for_rows(included_rows, report, window_id)
        coverage.append(window_coverage)
        if not _coverage_meets_gate(window_coverage):
            reasons.append(
                f"{window_id} does not reach the dual "
                f"{COVERAGE_THRESHOLD:.0%} coverage gate"
            )

    base_rows = [
        row for row in included_rows if row.get("selection_basis") == "scope_required"
    ]
    all_stable_gap_rows = _stable_residual_rows(
        report_indexes,
        window_ids,
        {LogSelector.from_mapping(row) for row in base_rows},
    )
    stable_gap_rows, out_of_scope_rows = _classify_residual_rows(
        all_stable_gap_rows,
        rows,
        out_of_scope_rules or [],
        reasons,
    )
    recommended_gap_rows = _smallest_residual_set(
        base_rows, stable_gap_rows, reports, window_ids
    )
    current_gap_rows = [
        row for row in included_rows if row.get("selection_basis") == "pareto_gap"
    ]
    if recommended_gap_rows is not None and {
        LogSelector.from_mapping(row) for row in recommended_gap_rows
    } != {LogSelector.from_mapping(row) for row in current_gap_rows}:
        if not recommended_gap_rows:
            for row in current_gap_rows:
                reasons.append(
                    f"ledger row {rows.index(row) + 1} is a redundant "
                    "pareto_gap selection"
                )
        else:
            reasons.append(
                "ledger pareto_gap selection is not the smallest stable residual set"
            )

    return {
        "schema_version": 1,
        "validity": {"valid": not reasons, "reasons": reasons},
        "coverage": coverage,
        "residual_pareto": {
            "stable_candidate_count": len(stable_gap_rows),
            "out_of_scope": out_of_scope_rows,
            "recommended_selectors": (
                [
                    LogSelector.from_mapping(row).as_dict()
                    for row in recommended_gap_rows
                ]
                if recommended_gap_rows is not None
                else None
            ),
        },
        "rows": rows,
    }
