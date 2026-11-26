"""QPUProvider over QDMI devices: the bundled DDSIM simulator for now.

Requires the ``quantum`` extra: ``pip install q99-utils[quantum]``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from q99_utils.integrations.core.exceptions import IntegrationError, ResourceNotFound
from q99_utils.quantum import _driver
from q99_utils.quantum.types import JobRef, JobResult, JobStatus


class QDMIProvider:
    """Runs OpenQASM 3 programs on QDMI devices.

    Job handles live in this object: DDSIM can't look a job up by id again, so
    re-attaching after a restart is left to devices that support it.
    """

    def __init__(self) -> None:
        self._devices: dict[str, Any] = {}
        self._jobs: dict[str, Any] = {}

    async def submit(self, device_id: str, program: str, shots: int) -> JobRef:
        device = await self._device(device_id)
        job = await asyncio.to_thread(_driver.submit_qasm3, device, program, shots)
        ref = JobRef(device_id=device_id, vendor_job_id=_driver.job_id(job), shots=shots)
        self._jobs[ref.vendor_job_id] = job
        return ref

    async def get_status(self, job: JobRef) -> JobStatus:
        return JobStatus(await asyncio.to_thread(_driver.job_status, self._job(job)))

    async def get_result(self, job: JobRef) -> JobResult:
        status = await self.get_status(job)
        if status is not JobStatus.DONE:
            raise IntegrationError(f"Job {job.vendor_job_id} has no result: it is {status}.")
        counts = await asyncio.to_thread(_driver.job_counts, self._job(job))
        return JobResult(counts=counts, shots=job.shots, status=status)

    async def _device(self, device_id: str) -> Any:
        if device_id not in self._devices:
            self._devices[device_id] = await asyncio.to_thread(_driver.open_device, device_id)
        return self._devices[device_id]

    def _job(self, job: JobRef) -> Any:
        try:
            return self._jobs[job.vendor_job_id]
        except KeyError:
            raise ResourceNotFound(f"Unknown job {job.vendor_job_id}.") from None


__all__ = ["QDMIProvider"]
