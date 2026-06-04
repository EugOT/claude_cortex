"""Adaptive batch-size controller — AIMD congestion control for batch writes.

Pure business logic — no I/O.

Grows the batch size additively while observed write latency stays within
target and shrinks it multiplicatively when latency exceeds target. AIMD is
the control law proven to converge to efficiency *and* fairness — additive
increase / multiplicative decrease is the unique combination that does
(Chiu & Jain 1989) — and is TCP's congestion-window algorithm (Jacobson 1988).
Using latency (not loss) as the congestion signal follows SEDA's adaptive
admission controller (Welsh et al. 2001).
"""

from __future__ import annotations

from dataclasses import dataclass

# source: Jacobson, V. (1988) "Congestion Avoidance and Control", SIGCOMM '88 —
# multiplicative decrease halves the window on congestion. Chiu & Jain (1989)
# prove multiplicative decrease is necessary for convergence. β = 0.5 is the
# TCP Reno value.
_MD_FACTOR = 0.5


@dataclass
class AdaptiveBatchController:
    """AIMD state machine; the SOLE owner of the live batch size ``B``.

    ``b_min``, ``b_max`` and ``w_target_s`` MUST come from the calibration
    sweep (benchmarks/streaming_calibration), never invented constants.

    ``b_max`` is a hard upper bound the controller can never exceed: the
    pipeline sizes its bounded queue from ``b_max`` (not the live B), so the
    RAM invariant ``(Q + c + 1)·b_max·row_bytes`` holds even after B ramps up.

    ``ai_step`` — additive-increase increment per control interval. Jacobson's
    unit is one MSS (the smallest sendable segment); the analog here is one
    minimum batch, so it defaults to ``b_min``. source: Jacobson 1988
    (one unit / interval).
    """

    b_min: int
    b_max: int
    w_target_s: float
    ai_step: int = 0  # resolved to b_min in __post_init__ when left 0
    _b: int = 0

    def __post_init__(self) -> None:
        if not 0 < self.b_min <= self.b_max:
            raise ValueError(
                f"require 0 < b_min <= b_max, got {self.b_min}, {self.b_max}"
            )
        if self.w_target_s <= 0:
            raise ValueError(f"w_target_s must be positive, got {self.w_target_s}")
        if self.ai_step <= 0:
            self.ai_step = self.b_min
        self._b = self.b_min

    @property
    def batch_size(self) -> int:
        """The current batch size ``B`` (b_min <= B <= b_max)."""
        return self._b

    def observe(self, latency_s: float) -> int:
        """Update B from one observed batch-write latency; return the new B.

        Within target → additive increase ``B += ai_step``; over target →
        multiplicative decrease ``B := max(b_min, floor(beta * B))``.
        Postcondition: ``b_min <= B <= b_max``.
        """
        if latency_s <= self.w_target_s:
            self._b = min(self.b_max, self._b + self.ai_step)
        else:
            self._b = max(self.b_min, int(self._b * _MD_FACTOR))
        assert self.b_min <= self._b <= self.b_max  # invariant (precond 4)
        return self._b
