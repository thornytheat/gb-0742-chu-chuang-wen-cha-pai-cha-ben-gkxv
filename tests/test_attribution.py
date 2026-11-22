from app.modules.attribution.attribution import COMMON, INSUFFICIENT, SINGLE, attribute
from app.modules.episodes.segment import segment
from app.timebase import utc


def _slot(cabinet, hour, state, upper=None, lower=None):
    base = 1_700_000_000
    hour_start = base - base % 3600 + hour * 3600
    return {"cabinet": cabinet, "hour": hour_start, "start": utc(hour_start), "end": utc(hour_start + 3600),
            "state": state, "axes": ["temperature"] if state == "ABNORMAL" else [],
            "upper": upper or f"{cabinet}-U{hour}", "lower": lower or f"{cabinet}-L{hour}"}


def _cabinet(identifier):
    class Model:
        id = identifier
    return Model()


def _spec(cabinets):
    class Shift:
        cabinet_hours = [_cabinet(item) for item in cabinets]
        sustained_hours = 2
    return Shift()


def _episodes(grades):
    return segment(grades, 2)


def test_overlapping_abnormal_episodes_merge_into_common_event():
    grades = [_slot("CV-17", 1, "ABNORMAL"), _slot("CV-17", 2, "ABNORMAL"),
              _slot("CV-21", 1, "ABNORMAL"), _slot("CV-21", 2, "ABNORMAL"),
              _slot("CV-17", 0, "STABLE"), _slot("CV-21", 0, "STABLE")]
    report = attribute(_spec(["CV-17", "CV-21"]), grades, _episodes(grades))
    assert report["counts"][COMMON] == 2
    assert len(report["events"]) == 1
    event = report["events"][0]
    assert event["cabinets"] == ["CV-17", "CV-21"] and event["episodes"] == ["CV-17-A01", "CV-21-A01"]
    for verdict in report["verdicts"]:
        assert verdict["verdict"] == COMMON and verdict["event"] == "ENV-E01" and verdict["retained"] is False
    shared = report["verdicts"][0]["shared_evidence"]
    assert [(item["cabinet"], item["state"]) for item in shared] == [("CV-21", "ABNORMAL"), ("CV-21", "ABNORMAL")]
    assert all(item["upper"] and item["lower"] for item in shared)


def test_single_cabinet_episode_needs_stable_counter_evidence_every_hour():
    grades = [_slot("CV-17", 1, "ABNORMAL"), _slot("CV-17", 2, "ABNORMAL"),
              _slot("CV-21", 1, "STABLE"), _slot("CV-21", 2, "STABLE"),
              _slot("CV-17", 0, "STABLE"), _slot("CV-21", 0, "STABLE")]
    report = attribute(_spec(["CV-17", "CV-21"]), grades, _episodes(grades))
    verdict = report["verdicts"][0]
    assert verdict["verdict"] == SINGLE and verdict["event"] is None and verdict["retained"] is False
    assert {item["state"] for item in verdict["counter_evidence"]} == {"STABLE"}
    assert verdict["gaps"] == [] and report["events"] == []


def test_missing_counter_evidence_retains_original_episode():
    grades = [_slot("CV-17", 1, "ABNORMAL"), _slot("CV-17", 2, "ABNORMAL"),
              _slot("CV-21", 1, "STABLE"), _slot("CV-21", 2, "MISSING"),
              _slot("CV-17", 0, "STABLE"), _slot("CV-21", 0, "STABLE")]
    report = attribute(_spec(["CV-17", "CV-21"]), grades, _episodes(grades))
    verdict = report["verdicts"][0]
    assert verdict["verdict"] == INSUFFICIENT and verdict["retained"] is True
    assert report["retained"] == ["CV-17-A01"]
    assert verdict["gaps"] == [{"cabinet": "CV-21", "hour": verdict["counter_evidence"][1]["hour"]}]


def test_missing_whole_hour_in_other_cabinet_is_also_insufficient():
    grades = [_slot("CV-17", 1, "ABNORMAL"), _slot("CV-17", 2, "ABNORMAL"),
              _slot("CV-21", 1, "STABLE"),
              _slot("CV-17", 0, "STABLE"), _slot("CV-21", 0, "STABLE")]
    report = attribute(_spec(["CV-17", "CV-21"]), grades, _episodes(grades))
    verdict = report["verdicts"][0]
    assert verdict["verdict"] == INSUFFICIENT
    missing = [item for item in verdict["counter_evidence"] if item["state"] == "MISSING"]
    assert len(missing) == 1 and missing[0]["upper"] is None and missing[0]["lower"] is None


def test_partial_overlap_still_groups_common_event():
    # CV-17 异常 [1,3)，CV-21 异常 [2,4)，仅第 2 小时重叠。
    grades = [_slot("CV-17", 1, "ABNORMAL"), _slot("CV-17", 2, "ABNORMAL"),
              _slot("CV-21", 2, "ABNORMAL"), _slot("CV-21", 3, "ABNORMAL"),
              _slot("CV-17", 0, "STABLE"), _slot("CV-17", 3, "STABLE"),
              _slot("CV-21", 0, "STABLE"), _slot("CV-21", 1, "STABLE")]
    report = attribute(_spec(["CV-17", "CV-21"]), grades, _episodes(grades))
    assert report["counts"][COMMON] == 2 and len(report["events"]) == 1
    assert [item["hour"][11:13] for item in report["verdicts"][0]["shared_evidence"]] == ["00"]


def test_same_cabinet_episodes_are_never_joined():
    grades = [_slot("CV-17", 1, "ABNORMAL"), _slot("CV-17", 2, "STABLE"),
              _slot("CV-17", 3, "ABNORMAL"), _slot("CV-17", 4, "ABNORMAL"),
              _slot("CV-21", 1, "STABLE"), _slot("CV-21", 2, "STABLE"),
              _slot("CV-21", 3, "STABLE"), _slot("CV-21", 4, "STABLE")]
    report = attribute(_spec(["CV-17", "CV-21"]), grades, _episodes(grades))
    assert report["events"] == []
    assert [item["episode"] for item in report["verdicts"]] == ["CV-17-A01", "CV-17-A02"]
    assert all(item["verdict"] == SINGLE for item in report["verdicts"])


def test_three_cabinets_chain_into_one_environment_event():
    grades = [_slot("CV-17", 1, "ABNORMAL"), _slot("CV-17", 2, "ABNORMAL"),
              _slot("CV-21", 1, "ABNORMAL"), _slot("CV-21", 2, "ABNORMAL"),
              _slot("CV-33", 2, "ABNORMAL"), _slot("CV-33", 3, "ABNORMAL"),
              _slot("CV-17", 0, "STABLE"), _slot("CV-21", 0, "STABLE"),
              _slot("CV-33", 0, "STABLE"), _slot("CV-17", 3, "STABLE"),
              _slot("CV-21", 3, "STABLE")]
    report = attribute(_spec(["CV-17", "CV-21", "CV-33"]), grades, _episodes(grades))
    assert len(report["events"]) == 1
    assert report["events"][0]["cabinets"] == ["CV-17", "CV-21", "CV-33"]
    assert report["counts"][COMMON] == 3


def test_single_cabinet_shift_cannot_confirm_single_responsibility():
    grades = [_slot("CV-17", 1, "ABNORMAL"), _slot("CV-17", 2, "ABNORMAL"), _slot("CV-17", 0, "STABLE")]
    report = attribute(_spec(["CV-17"]), grades, _episodes(grades))
    assert report["counts"][INSUFFICIENT] == 1 and report["verdicts"][0]["retained"] is True


def test_attribution_is_deterministic_and_order_independent():
    grades = [_slot("CV-17", 1, "ABNORMAL"), _slot("CV-17", 2, "ABNORMAL"),
              _slot("CV-21", 1, "ABNORMAL"), _slot("CV-21", 2, "ABNORMAL"),
              _slot("CV-17", 0, "STABLE"), _slot("CV-21", 0, "STABLE")]
    spec = _spec(["CV-17", "CV-21"])
    first = attribute(spec, grades, _episodes(grades))
    shuffled = attribute(spec, list(reversed(grades)), _episodes(list(reversed(grades))))
    assert first == shuffled


def test_closure_sample_covers_all_three_verdicts(snapshot_closure):
    report = snapshot_closure["attribution"]
    assert report["counts"] == {COMMON: 2, SINGLE: 1, INSUFFICIENT: 1}
    assert report["retained"] == ["CV-17-A02"]
    by_episode = {item["episode"]: item for item in report["verdicts"]}
    assert by_episode["CV-33-A01"]["verdict"] == SINGLE
    assert by_episode["CV-17-A01"]["event"] == by_episode["CV-21-A01"]["event"] == "ENV-E01"
