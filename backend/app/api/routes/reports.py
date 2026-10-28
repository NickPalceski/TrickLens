"""Reports from the app (F4): "Report a problem with this analysis" and
"Report a bug". See docs/components/frontend.md, Reports.

Stored in `reports` and read with `make reports` (app/reports.py). Never
forwarded to GitHub issues: the repo is public.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, OptionalUser
from app.models.clip import Clip
from app.models.enums import ClipStatus, ReportKind
from app.models.report import Report
from app.schemas.report import AnalysisReportCreate, BugReportCreate, ReportCreated

router = APIRouter(tags=["reports"])

# Before publishing is when the skater sees the result; reporting a
# published clip's analysis isn't offered (yet).
_REPORTABLE = (ClipStatus.ANALYZED, ClipStatus.UNANALYZABLE)


@router.post("/clips/{clip_id}/analysis-reports", status_code=status.HTTP_201_CREATED)
async def report_analysis(
    clip_id: uuid.UUID, body: AnalysisReportCreate, user: CurrentUser, db: DbSession
) -> ReportCreated:
    """Your own clip, analyzed or couldn't be scored. Never changes the
    score or the clip's status. The server snapshots the analysis as it is
    now; with `share_video`, the snapshot also records the processed
    video's key (the transcode under processed/ isn't deleted, unlike the
    raw upload)."""
    clip = await db.scalar(select(Clip).where(Clip.id == clip_id))
    if clip is None or clip.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "clip not found")
    if clip.status not in _REPORTABLE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "only an analyzed clip, or one that couldn't be scored, can be reported",
        )
    latest = clip.analyses[0] if clip.analyses else None
    if latest is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "this clip was not analyzed")
    if not body.problems and not (body.note or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "say what went wrong")
    analyzed = len((latest.details or {}).get("tricks", []))
    if body.trick_index is not None and body.trick_index >= analyzed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"trick_index {body.trick_index} is out of range: the analysis found {analyzed}",
        )

    report = Report(
        kind=ReportKind.ANALYSIS,
        user_id=user.id,
        clip_id=clip.id,
        body=body.model_dump(mode="json"),
        analysis={
            "analysis_id": str(latest.id),
            "model_version": latest.model_version,
            "confidence": str(latest.confidence),
            "steeze_score": str(clip.steeze_score) if clip.steeze_score is not None else None,
            "steeze_breakdown": latest.steeze_breakdown,
            "failure_reason": latest.failure_reason,
            "details": latest.details,
            "tags": [
                {"name": ct.trick.canonical_name, "analysis_index": ct.analysis_index}
                for ct in clip.clip_tricks
            ],
            "video_key": clip.processed_key if body.share_video else None,
        },
        share_video=body.share_video,
    )
    db.add(report)
    await db.flush()
    await db.refresh(report, attribute_names=["created_at"])
    return ReportCreated(id=report.id, created_at=report.created_at)


@router.post("/bug-reports", status_code=status.HTTP_201_CREATED)
async def report_bug(body: BugReportCreate, viewer: OptionalUser, db: DbSession) -> ReportCreated:
    """Signed in or out (a broken login is a bug too). Signed in, the report
    records who sent it, so we can follow up. API Gateway throttles this
    route on its own (infra/api_gateway.tf), since anyone can call it."""
    report = Report(
        kind=ReportKind.BUG,
        user_id=viewer.id if viewer else None,
        body=body.model_dump(mode="json"),
    )
    db.add(report)
    await db.flush()
    await db.refresh(report, attribute_names=["created_at"])
    return ReportCreated(id=report.id, created_at=report.created_at)
