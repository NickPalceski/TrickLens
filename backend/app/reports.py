"""Read the reports people send from the app (F4).

    python -m app.reports                    # the 20 newest
    python -m app.reports --kind bug --limit 50
    python -m app.reports --days 7           # only the last week
    python -m app.reports --id <uuid>        # one report in full, as JSON

`make reports` runs it against the local database. For prod, pass the
Neon URL the same way the migrate job gets it (docs/deployment.md,
Reading reports). Never from a GitHub Actions job: the repo is public, and
so are its job logs.

Database only and synchronous, through the DB-only settings Alembic uses
(get_migration_settings), like app/rescore.py.
"""

import argparse
import json
import sys
import textwrap
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import get_migration_settings
from app.models.enums import ReportKind
from app.models.report import Report
from app.models.user import User


def _wrap(text: str, indent: str = "    ") -> str:
    return textwrap.fill(
        " ".join(text.split()), width=88, initial_indent=indent, subsequent_indent=indent
    )


def format_report(r: Report, username: str | None) -> str:
    """A few readable lines; `--id` shows everything."""
    who = f"@{username}" if username else "signed out"
    head = f"{r.created_at:%Y-%m-%d %H:%M} UTC  {r.kind.value:<8}  {r.id}  {who}"
    b, lines = r.body, [head]
    if r.kind is ReportKind.BUG:
        ctx = b.get("context", {})
        lines.append(_wrap(b.get("description", "")))
        lines.append(
            f"    page {b.get('page') or '-'} | app {ctx.get('app_version')} | "
            f"{ctx.get('viewport')} | {ctx.get('theme')} | {ctx.get('api_mode')}"
        )
        lines.append(f"    {ctx.get('user_agent', '')[:120]}")
    else:
        a = r.analysis or {}
        problems = ", ".join(b.get("problems", [])) or "-"
        which = "whole clip" if b.get("trick_index") is None else f"trick {b['trick_index'] + 1}"
        lines.append(f"    clip {r.clip_id} | {problems} | {which}")
        if b.get("subscores") or b.get("score_direction"):
            subs = ", ".join(b.get("subscores", [])) or "-"
            lines.append(f"    subscores {subs} feel {b.get('score_direction') or '-'}")
        if b.get("note"):
            lines.append(_wrap(b["note"]))
        result = a.get("failure_reason") or f"steeze {a.get('steeze_score')}"
        lines.append(f"    {a.get('model_version')} | {result} | app {b.get('app_version') or '-'}")
        lines.append(
            f"    video shared: {a['video_key']}" if r.share_video else "    video not shared"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read reports sent from the app.")
    ap.add_argument("--kind", choices=[k.value for k in ReportKind])
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--days", type=float, help="only reports from the last N days")
    ap.add_argument("--id", type=uuid.UUID, help="show one report in full, as JSON")
    args = ap.parse_args(argv)

    engine = create_engine(get_migration_settings().sync_url, pool_pre_ping=True)
    with Session(engine) as db:
        stmt = select(Report, User.username).outerjoin(User, User.id == Report.user_id)
        if args.id:
            row = db.execute(stmt.where(Report.id == args.id)).first()
            if row is None:
                print(f"no report {args.id}", file=sys.stderr)
                return 1
            r, username = row
            full = {
                "id": str(r.id),
                "kind": r.kind.value,
                "created_at": r.created_at.isoformat(),
                "user": username,
                "clip_id": str(r.clip_id) if r.clip_id else None,
                "share_video": r.share_video,
                "body": r.body,
                "analysis": r.analysis,
            }
            print(json.dumps(full, indent=2))
            return 0

        if args.kind:
            stmt = stmt.where(Report.kind == ReportKind(args.kind))
        if args.days:
            stmt = stmt.where(Report.created_at >= datetime.now(UTC) - timedelta(days=args.days))
        rows = db.execute(stmt.order_by(Report.created_at.desc()).limit(args.limit)).all()

    for r, username in rows:
        print(format_report(r, username), end="\n\n")
    print(f"{len(rows)} report(s), newest first")
    return 0


if __name__ == "__main__":
    sys.exit(main())
