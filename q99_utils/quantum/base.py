"""The contract every quantum provider implements."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from q99_utils.quantum.types import JobRef, JobResult, JobStatus


@runtime_checkable
class QPUProvider(Protocol):
    """Runs programs on one vendor's quantum devices (or a simulator).

    A job can wait hours in a vendor's queue, so submitting and collecting are
    separate calls: keep the ``JobRef`` and ask again later.
    """

    async def submit(self, device_id: str, program: str, shots: int) -> JobRef:
        """Send an OpenQASM 3 program; returns at once, before it runs."""
        ...

    async def get_status(self, job: JobRef) -> JobStatus: ...

    async def get_result(self, job: JobRef) -> JobResult:
        """The measurements of a DONE job; any other state raises."""
        ...


__all__ = ["QPUProvider"]
