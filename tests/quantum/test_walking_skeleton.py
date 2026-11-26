"""SCRUM-851 acceptance scenarios: a toy circuit runs end to end through QPUProvider."""

import asyncio
import importlib
import sys

import pytest

from q99_utils.quantum import JobStatus, QPUProvider

BELL = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
bit[2] c;
h q[0];
cx q[0], q[1];
c = measure q;
"""

FINISHED = {JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELED}


async def _wait(provider, job, timeout_s=30.0):
    deadline = asyncio.get_running_loop().time() + timeout_s
    while (status := await provider.get_status(job)) not in FINISHED:
        if asyncio.get_running_loop().time() > deadline:
            pytest.fail(f"job still {status} after {timeout_s} s")
        await asyncio.sleep(0.05)
    return status


async def test_a_bell_circuit_runs_on_the_simulator():
    # Given the [quantum] extra is installed
    pytest.importorskip("mqt.core.qdmi", reason="needs q99-utils[quantum]")
    from q99_utils.quantum.qdmi import QDMIProvider

    # And a QDMIProvider for the device "mqt.ddsim.default"
    provider = QDMIProvider()
    assert isinstance(provider, QPUProvider)

    # When I submit a 2-qubit Bell circuit with 1000 shots
    job = await provider.submit("mqt.ddsim.default", BELL, shots=1000)

    # Then the job status becomes DONE
    assert await _wait(provider, job) == JobStatus.DONE

    # And the result counts contain only "00" and "11"
    result = await provider.get_result(job)
    assert set(result.counts) <= {"00", "11"}

    # And the counts sum to 1000
    assert sum(result.counts.values()) == 1000
    assert result.shots == 1000


def test_the_quantum_package_without_the_extra(monkeypatch):
    # Given the [quantum] extra is not installed
    for name in ("mqt", "mqt.core", "mqt.core.qdmi"):
        monkeypatch.setitem(sys.modules, name, None)
    package = importlib.import_module("q99_utils.quantum")
    for name in ("qdmi", "_driver"):
        monkeypatch.delitem(sys.modules, f"q99_utils.quantum.{name}", raising=False)
        monkeypatch.delattr(package, name, raising=False)

    # When I import the QDMI provider
    # Then I get a clear error telling me to install q99-utils[quantum]
    with pytest.raises(ImportError, match=r"q99-utils\[quantum\]"):
        importlib.import_module("q99_utils.quantum.qdmi")
