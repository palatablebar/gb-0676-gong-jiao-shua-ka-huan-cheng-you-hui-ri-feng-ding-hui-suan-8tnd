import csv, io
import pytest
from app.pipeline import execute, load_sample
from app import store
from app.modules.m2_routes.stations import DEFAULT_PROFILE
from app.errors import DomainError


def test_rerun_does_not_double_occupy_quota():
    "同一批重跑：批次与卡日台账都不新增"
    raw = load_sample("clean.csv")
    first = execute(raw)
    second = execute(raw)
    assert first["run_id"] == second["run_id"]
    assert len(store.history()) == 1
    quota = store.occupied_quota()
    assert len(quota) == second["stages"][6]["metrics"]["receivables"]
    assert all(q["runs"] == 1 for q in quota)


def test_unique_receivable_matches_settlement():
    run = execute(load_sample("clean.csv"))
    receivables = run["stages"][6]["receivables"]
    keys = [r["receivable_key"] for r in receivables]
    assert len(keys) == len(set(keys))
    assert all(len(key.split("|")) == 2 for key in keys)


def test_profile_switch_is_atomic_on_validation_failure():
    "校验失败不写入，旧资料与旧日账完整"
    old = execute(load_sample("clean.csv"))
    with pytest.raises(DomainError):
        store.switch_profile({"version": "BROKEN", "limits": {"normal": 90, "hub": 60}, "stations": DEFAULT_PROFILE["stations"]})
    assert store.active_profile() == store.active_profile()
    assert store.profile_history() == []
    assert store.get(old["run_id"])["stages"][6]["rows"] == old["stages"][6]["rows"]


def test_profile_switch_keeps_old_ledger_and_adds_version():
    old = execute(load_sample("clean.csv"))
    profile = {**DEFAULT_PROFILE, "version": "SP-2026.12.01"}
    result = store.switch_profile(profile)
    assert result["active"] and not result["unchanged"]
    assert store.active_profile()["version"] == "SP-2026.12.01"
    assert len(store.profile_history()) == 1
    assert store.get(old["run_id"])["stages"][6]["rows"] == old["stages"][6]["rows"]


def test_same_profile_twice_is_idempotent():
    profile = {**DEFAULT_PROFILE, "version": "SP-2026.12.02"}
    store.switch_profile(profile)
    again = store.switch_profile(profile)
    assert again["unchanged"] and len(store.profile_history()) == 1


def test_profile_version_conflict_rejected():
    profile = {**DEFAULT_PROFILE, "version": "SP-2026.12.03"}
    store.switch_profile(profile)
    with pytest.raises(DomainError) as e:
        store.switch_profile({**profile, "limits": {"normal": 50, "hub": 80}})
    assert e.value.code == "PROFILE_VERSION_CONFLICT"


def test_pending_basis_blocks_seal(client):
    "依据未核清前不能封存"
    profile = {**DEFAULT_PROFILE, "version": "SP-PENDING",
               "stations": {**DEFAULT_PROFILE["stations"], "02": {"station": "北门站", "type": "normal", "verified": False}}}
    p = client.post("/api/runs", json={"sample": "clean.csv", "parameters": {"station_profile": profile}}).get_json()
    assert p["stages"][6]["metrics"]["pending_basis"] > 0
    r = client.post("/api/runs/" + p["run_id"] + "/review", json={"version": 1, "decision": "已复核"})
    assert r.status_code == 409 and r.get_json()["code"] == "UNVERIFIED_BASIS"


def test_verified_profile_seals(client):
    p = client.post("/api/runs", json={"sample": "clean.csv"}).get_json()
    assert p["stages"][6]["metrics"]["pending_basis"] == 0
    assert client.post("/api/runs/" + p["run_id"] + "/review", json={"version": 1, "decision": "已复核"}).status_code == 200


def test_archive_carries_station_basis_and_receivable(client):
    p = client.post("/api/runs", json={"sample": "clean.csv"}).get_json()
    r = client.get("/api/runs/" + p["run_id"] + "/archive")
    rows = list(csv.reader(io.StringIO(r.data.decode("utf-8-sig"))))
    header = rows[0]
    assert "station_profile" in header
    accepted = [x for x in rows[1:] if x[3] == "accepted"]
    assert accepted and "station_basis" in accepted[0][header.index("evidence")]
    assert any(x[3] == "receivable" for x in rows[1:])


def test_stations_endpoint_roundtrip(client):
    current = client.get("/api/stations").get_json()
    assert current["active"]["version"] == DEFAULT_PROFILE["version"]
    body = {**DEFAULT_PROFILE, "version": "SP-2026.12.09"}
    assert client.post("/api/stations", json=body).status_code == 200
    assert client.get("/api/stations").get_json()["active"]["version"] == "SP-2026.12.09"
    bad = {"version": "SP-BAD", "limits": {"normal": 0, "hub": 90}, "stations": DEFAULT_PROFILE["stations"]}
    assert client.post("/api/stations", json=bad).status_code == 422
    assert client.get("/api/stations").get_json()["active"]["version"] == "SP-2026.12.09"


def test_switch_profile_changes_next_run_not_old_ledger():
    "切换站点资料后重跑用新时限，旧批次日账保持原样"
    old = execute(load_sample("hub.csv"))
    assert old["parameters"]["station_profile"]["version"] == DEFAULT_PROFILE["version"]
    tighter = {**DEFAULT_PROFILE, "version": "SP-TIGHT", "limits": {"normal": 60, "hub": 70}}
    store.switch_profile(tighter)
    new = execute(load_sample("hub.csv"))
    assert new["parameters"]["station_profile"]["version"] == "SP-TIGHT"
    assert new["run_id"] != old["run_id"]
    assert store.get(old["run_id"])["stages"][4]["rows"] == old["stages"][4]["rows"]
    old_hub = [r for r in old["stages"][4]["rows"] if r["event_id"] == "0102"][0]
    new_hub = [r for r in new["stages"][4]["rows"] if r["event_id"] == "0102"][0]
    assert old_hub["transfer_limit"] == 90 and old_hub["expected"] == "1.50"
    assert new_hub["transfer_limit"] == 70
