import math
from dataclasses import dataclass


@dataclass(frozen=True)
class VisualFact:
    candidate: str
    outcome: str
    score: float | None
    threshold: float | None
    duration_ms: int

    def __post_init__(self):
        if not self.candidate or len(self.candidate) > 64:
            raise ValueError("candidate must contain 1 to 64 characters")
        if self.outcome not in {"matched", "missed", "invalid", "missing"}:
            raise ValueError("unsupported visual outcome")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")
        for value in (self.score, self.threshold):
            if value is not None and not math.isfinite(value):
                raise ValueError("score and threshold must be finite")

    @property
    def threshold_distance(self) -> float | None:
        if self.score is None or self.threshold is None:
            return None
        return abs(self.score - self.threshold)


class RepresentativeVisualFacts:
    """Keep only the finite representatives required by the visual log contract."""

    def __init__(self):
        self._closest = {}
        self._slowest = None
        self._first_invalid = None
        self._selected = None

    def add(self, fact: VisualFact) -> None:
        if fact.threshold_distance is not None:
            previous = self._closest.get(fact.candidate)
            if (
                previous is None
                or fact.threshold_distance < previous.threshold_distance
            ):
                self._closest[fact.candidate] = fact
            if len(self._closest) > 3:
                farthest = max(
                    self._closest.values(),
                    key=lambda item: (item.threshold_distance, item.candidate),
                )
                del self._closest[farthest.candidate]

        if self._slowest is None or fact.duration_ms > self._slowest.duration_ms:
            self._slowest = fact
        if self._first_invalid is None and fact.outcome in {"invalid", "missing"}:
            self._first_invalid = fact
        if fact.outcome == "matched":
            self._selected = fact

    def snapshot(self) -> tuple[VisualFact, ...]:
        ordered = []
        if self._selected is not None:
            ordered.append(self._selected)
        ordered.extend(
            sorted(
                self._closest.values(),
                key=lambda item: (item.threshold_distance, item.candidate),
            )
        )
        if self._slowest is not None:
            ordered.append(self._slowest)
        if self._first_invalid is not None:
            ordered.append(self._first_invalid)

        result = []
        candidates = set()
        for fact in ordered:
            if fact.candidate in candidates:
                continue
            result.append(fact)
            candidates.add(fact.candidate)
        return tuple(result)
