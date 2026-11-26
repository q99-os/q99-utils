"""The only module that touches MQT Core's QDMI driver.

Keeping every ``mqt.core.qdmi`` call here means the next MQT Core upgrade
changes one file. The calls are blocking (C code holding the GIL); callers run
them off the event loop.
"""

from __future__ import annotations

from typing import Any

try:
    from mqt.core import qdmi
except ImportError as exc:
    if (exc.name or "").split(".")[0] != "mqt":
        raise
    raise ImportError(
        "Quantum providers need MQT Core: install q99-utils[quantum]", name=exc.name
    ) from exc


def open_device(device_id: str) -> Any:
    return qdmi.open_device(device_id)


def submit_qasm3(device: Any, program: str, shots: int) -> Any:
    return device.submit_job(program, qdmi.ProgramFormat.QASM3, shots)


def job_id(job: Any) -> str:
    return str(job.id)


def job_status(job: Any) -> str:
    """The QDMI status name, e.g. ``"DONE"``."""
    return job.check().name


def job_counts(job: Any) -> dict[str, int]:
    """Counts in QDMI bit order, which is already Qiskit's (rightmost = qubit 0)."""
    return {str(key): int(value) for key, value in job.get_counts().items()}


__all__ = ["job_counts", "job_id", "job_status", "open_device", "submit_qasm3"]
