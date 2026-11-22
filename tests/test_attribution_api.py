from app.manifest import json_sha


def _run(client, sample="closure"):
    response = client.post("/api/runs", json={"sample": sample})
    assert response.status_code == 201, response.text
    base = f'/api/runs/{response.json()["manifest"]["id"]}'
    return base


def test_attribution_endpoint_lists_verdicts_and_environment_events(client):
    base = _run(client)
    data = client.get(base + "/attribution").json()
    assert data["counts"] == {"COMMON_EVENT": 2, "SINGLE_CABINET": 1, "INSUFFICIENT_EVIDENCE": 1}
    assert data["retained"] == ["CV-17-A02"]
    assert len(data["events"]) == 1 and data["events"][0]["cabinets"] == ["CV-17", "CV-21"]
    assert {item["verdict"] for item in data["verdicts"]} == set(data["counts"])


def test_handled_flag_marks_unhandled_sustained_episodes(client):
    base = _run(client)
    handled = {item["episode"]: item["handled"] for item in client.get(base + "/attribution").json()["verdicts"]}
    assert handled == {"CV-17-A01": True, "CV-21-A01": True, "CV-33-A01": False, "CV-17-A02": False}
    # 未处置段与值班单勾稽的缺工单清单一致。
    unreported = client.get(base + "/audit").json()["unreported"]
    assert sorted(name for name, done in handled.items() if not done) == sorted(unreported)


def test_attribution_can_be_scoped_to_one_cabinet_and_unknown_cabinet_is_404(client):
    base = _run(client)
    data = client.get(base + "/attribution/CV-33").json()
    assert [item["episode"] for item in data["verdicts"]] == ["CV-33-A01"]
    assert data["events"]  # 事件清单仍为班次视角
    missing = client.get(base + "/attribution/CV-99")
    assert (missing.status_code, missing.json()["code"]) == (404, "UNKNOWN_CABINET")


def test_handled_flag_follows_ticket_reconciliation(client):
    base = _run(client, "shift")
    data = client.get(base + "/attribution").json()
    handled = {item["episode"]: item["handled"] for item in data["verdicts"]}
    assert handled == {"CV-17-A01": True, "CV-17-A02": False, "CV-17-A03": False}


def test_export_and_workbench_share_the_same_attribution_conclusion(client):
    base = _run(client)
    live = client.get(base + "/attribution").json()
    package = client.get(base + "/export").json()
    stored = package["evidence"]["attribution"]
    # 页面结论逐字来自同一版归卷证据（handled 为页面侧结合工单的派生标记，不入库）。
    for verdict in stored["verdicts"]:
        page_verdict = next(item for item in live["verdicts"] if item["episode"] == verdict["episode"])
        assert {key: value for key, value in page_verdict.items() if key != "handled"} == verdict
    assert stored["events"] == live["events"] and stored["counts"] == live["counts"]
    assert stored["retained"] == live["retained"]
    # 该版证据受结果摘要覆盖，两次下载字节一致。
    assert package["manifest"]["result_sha256"] == json_sha(package["evidence"])
    assert client.get(base + "/export").content == client.get(base + "/export").content


def test_rerun_same_shift_keeps_single_archive_and_identical_attribution(client):
    base = _run(client)
    before = client.get(base + "/attribution").json()
    assert client.post(base + "/rerun").json()["verified"] is True
    again = client.post("/api/runs", json={"sample": "closure"})
    assert again.status_code == 200 and again.json()["reused"] is True
    assert len(client.get("/api/runs").json()) == 1
    after = client.get(base + "/attribution").json()
    assert after == before


def test_failed_generation_keeps_previous_conclusion_untouched(client):
    base = _run(client, "shift")
    prior = client.get(base + "/attribution").json()
    failed = client.post("/api/runs", json={"sample": "truncated"})
    assert failed.status_code == 422
    assert client.get(base + "/attribution").json() == prior
    assert [item["id"] for item in client.get("/api/runs").json()] == [base.rsplit("/", 1)[1]]
