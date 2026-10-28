"""Reports from the app (F4): "Report a problem with this analysis" and
"Report a bug". See docs/components/frontend.md, Reports.

They stay in this table and are read with `make reports` (app/reports.py).
Never forwarded to GitHub issues: the repo is public.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, false, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKey
from app.models.enums import ReportKind, sa_enum


class Report(Base, UUIDPrimaryKey):
    """One report. Append-only.

    `body` is what the person sent, as validated by the route's schema.
    `analysis` is the server's own snapshot of the analysis being reported
    (model version, scores, `details`), taken when the report arrives, so a
    later rescore can't change what was reported. Both FKs are SET NULL: a
    report outlives the account or clip it came from.
    """

    __tablename__ = "reports"

    kind: Mapped[ReportKind] = mapped_column(sa_enum(ReportKind, "report_kind"), nullable=False)
    # Null for a bug reported while signed out.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    clip_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="SET NULL"), index=True
    )
    body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    analysis: Mapped[dict | None] = mapped_column(JSONB)
    # The skater's consent to keep and watch the clip. Only with it does the
    # snapshot record the processed video's key.
    share_video: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
