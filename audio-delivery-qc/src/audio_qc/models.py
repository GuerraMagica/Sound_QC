from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    INFO = "INFO"
    INCOMPLETE = "INCOMPLETE"


def highest_severity(severities) -> Status | None:
    """Preserve existing classifications in application order; never classify None."""
    present = set(severities)
    for status in (Status.INCOMPLETE, Status.FAIL, Status.WARNING, Status.PASS, Status.INFO):
        if status in present:
            return status
    return None


def overall_status(checks: list["Check"]) -> Status:
    for status in (Status.INCOMPLETE, Status.FAIL, Status.WARNING, Status.PASS):
        if any(c.status == status for c in checks):
            return status
    return Status.INFO


@dataclass
class Check:
    code: str
    status: Status
    message: str
    files: list[str] = field(default_factory=list)


class MeasurementState(StrEnum):
    SUCCESS = "SUCCESS"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class ExecutionStatus(StrEnum):
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


@dataclass(frozen=True)
class MeasurementOutcome:
    state: MeasurementState
    reason: str | None = None


@dataclass(frozen=True)
class OperationalDiagnostic:
    code: str
    message: str
    required: bool = False
    affects_analysis: bool = False


def execution_status(diagnostics, has_results=True, incomplete=False):
    if incomplete or any(d.required for d in diagnostics):
        return ExecutionStatus.PARTIAL if has_results else ExecutionStatus.FAILED
    return ExecutionStatus.COMPLETED_WITH_WARNINGS if diagnostics else ExecutionStatus.COMPLETED


@dataclass
class Defect:
    timestamp_seconds: float
    sample_index: int
    channel: int  # one-based source channel; sample indices are zero-based
    event_type: str
    duration_seconds: float
    severity: Status | None  # None until policy classifies a measured candidate
    measurements: dict[str, Any]
    detection_method: str
    snippet: str | None = None
    # Populated only on report copies; detector positions retain sample precision.
    timecode: str | None = None
    timecode_frame_rate: str | None = None
    timecode_basis: str | None = None
    file_start_timecode: str | None = None
    timecode_day_offset: int | None = None
    offset: str | None = None
    merged_candidate_count: int = 1
    cluster_first_sample: int | None = None
    cluster_last_sample: int | None = None  # inclusive; representative duration stays unchanged


@dataclass
class DefectIssue(Defect):
    """Measured operator-facing issue; legacy fields describe one representative.

    channel_events retain each channel's original representative and raw count.
    cluster bounds cover the complete issue, including all channel events.
    """
    channels: list[int] = field(default_factory=list)
    channel_events: list[Defect] = field(default_factory=list)


@dataclass
class AudioFile:
    path: str
    filename: str
    size_bytes: int | None = None
    duration_seconds: float | None = None
    decoded_duration_seconds: float | None = None
    sample_rate: int | None = None
    codec: str | None = None
    pcm_format: str | None = None
    bit_depth: int | None = None
    channels: int | None = None
    channel_layout: str | None = None
    stream_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    bwf: dict[str, Any] = field(default_factory=dict)
    measurements: dict[str, Any] = field(default_factory=dict)
    sha256: str | None = None
    audio_sha256: str | None = None
    checks: list[Check] = field(default_factory=list)
    defects: list[Defect] = field(default_factory=list)

    measurement_outcomes: dict[str, MeasurementOutcome] = field(default_factory=dict)
    operational_diagnostics: list[OperationalDiagnostic] = field(default_factory=list)

    @property
    def status(self) -> Status:
        if any(d.affects_analysis for d in self.operational_diagnostics):
            return Status.INCOMPLETE
        return overall_status(self.checks)

    @property
    def execution_status(self) -> ExecutionStatus:
        return execution_status(self.operational_diagnostics, "decoded_sample_frames" in self.measurements,
                                self.status == Status.INCOMPLETE)

    def operational(self, code, message, *, required=False, affects_analysis=False):
        self.operational_diagnostics.append(OperationalDiagnostic(code, str(message), required, affects_analysis))

    def add(self, code: str, status: Status, message: str) -> None:
        self.checks.append(Check(code, status, message))

    def to_dict(self) -> dict:
        return {"status": self.status.value, "audio_compliance": self.status.value,
                "execution_status": self.execution_status.value, **asdict(self)}


DEFECT_NOTICE = (
    "Automated defect detection identifies candidates for human QC review. "
    "It does not prove that an audible defect exists."
)
