"""A well whose ACTUAL definitive survey was never compiled: its drilled pass, stitched from the
measured survey runs. Depths are in feet, as the stations store them."""

from datetime import datetime

from q99_utils.integrations.mappers.openwells_edm import stitch_measured_runs


def _run(header: str, day: int | None, mds: list[float], azimuth: float | None = 10.0) -> list[dict]:
    dated = datetime(2026, 6, day) if day else None
    return [{"survey_header_id": header, "header_date": dated, "md": md, "tvd": md * 0.9, "inclination": 30.0,
             "azimuth": azimuth, "dogleg_severity": 1.0, "offset_north": md * 0.2, "offset_east": 0.0} for md in mds]


def test_runs_chain_by_md_and_the_newer_one_takes_the_tie_in_station():
    path = stitch_measured_runs(_run("S1", 1, [0, 500, 1000]) + _run("S2", 9, [1000, 2000, 3000]))
    assert [s["md"] for s in path] == [0, 500, 1000, 2000, 3000]
    assert [s["sequence_no"] for s in path] == [0, 1, 2, 3, 4]
    assert {s["phase"] for s in path} == {"ACTUAL"}


def test_a_newer_run_replaces_only_the_stretch_it_measured():
    path = stitch_measured_runs(_run("long", 1, [0, 1000, 2000, 3000]) + _run("remeasure", 9, [900, 1500, 2100]))
    assert [s["md"] for s in path] == [0, 900, 1500, 2100, 3000]


def test_impossible_stations_drop():
    bad = _run("S1", 1, [0, 1000, 450_000])
    bad.append({**bad[1], "md": 1200, "tvd": 1500})          # TVD past MD
    assert [s["md"] for s in stitch_measured_runs(bad)] == [0, 1000]


def test_an_inclination_only_run_stays_above_the_azimuth_data_and_never_below_it():
    drift = _run("TOTCO", 20, [0, 300, 4000, 6000], azimuth=0.0)       # newer, but no azimuth
    mwd = _run("MWD", 1, [300, 2000, 4500])
    # the drift keeps 0 m (above the MWD); 4000 m falls inside what the MWD measured; 6000 m is below it
    assert [s["md"] for s in stitch_measured_runs(drift + mwd)] == [0, 300, 2000, 4500]


def test_a_well_with_only_drift_runs_keeps_them():
    assert len(stitch_measured_runs(_run("drift", None, [0, 1000, 2000], azimuth=None))) == 3
