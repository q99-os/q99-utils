"""The values every quantum provider speaks, whatever the vendor."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    """QDMI's job states; every vendor's states map onto these."""

    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    CANCELED = "CANCELED"
    FAILED = "FAILED"


class JobRef(BaseModel):
    """What is kept to find a submitted job again."""

    device_id: str
    vendor_job_id: str
    shots: int = Field(gt=0)


class JobResult(BaseModel):
    """A finished job's measurements.

    ``counts`` keys are always in Qiskit bit order: the rightmost character is qubit 0.
    """

    counts: dict[str, int]
    shots: int
    status: JobStatus


__all__ = ["JobRef", "JobResult", "JobStatus"]
