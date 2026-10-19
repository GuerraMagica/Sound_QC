"""Execution inputs and technical state; no delivery-specification decisions."""
from dataclasses import dataclass


@dataclass(frozen=True)
class MeasurementRequirements:
    loudness: bool
    true_peak: bool
    defect_options: dict | None
    hash: bool = False
    timeout_seconds: float | None = None
    levels_required: bool = True

    @property
    def ebur128(self) -> bool:
        # The existing FFmpeg pass measures both loudness and true peak.
        return self.loudness or self.true_peak


@dataclass(frozen=True)
class ZeroRun:
    longest: int
    start: int


@dataclass
class MeasurementContext:
    zero_runs: tuple[ZeroRun, ...] = ()
    defects_unavailable: str | None = None
    defects_capped: bool = False
    source_signature: tuple[int, int, int] | None = None  # size, mtime_ns, inode
    source_change_error: str | None = None
