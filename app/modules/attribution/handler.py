from fastapi import APIRouter

from app.dependencies import Archive, cabinet_scope

router = APIRouter(prefix="/api/runs/{run_id}")


def _with_disposition(archive):
    snapshot = archive[1]
    attribution = snapshot["attribution"]
    matched = {ticket["episode"] for ticket in snapshot["audit"]["tickets"] if ticket["code"] == "MATCHED"}
    verdicts = [{**item, "handled": item["episode"] in matched} for item in attribution["verdicts"]]
    return {**attribution, "verdicts": verdicts}


@router.get("/attribution")
def attribution(archive: Archive):
    return _with_disposition(archive)


@router.get("/attribution/{cabinet}")
def attribution_by_cabinet(archive: Archive, cabinet: str):
    cabinet_scope(archive[0], cabinet)
    report = _with_disposition(archive)
    report["verdicts"] = [item for item in report["verdicts"] if item["cabinet"] == cabinet]
    return report
