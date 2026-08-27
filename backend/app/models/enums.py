"""Shared enums, mapped to native Postgres enum types.

Defined centrally so the API, the worker, and the database agree on the exact
same vocabulary.
"""

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class Stance(StrEnum):
    REGULAR = "regular"
    GOOFY = "goofy"


class SkateStyle(StrEnum):
    VERT = "vert"
    STREET = "street"
    MIX = "mix"


class ClipStatus(StrEnum):
    """Lifecycle of a clip.

    Defined now, used from step 3. The important property is that a clip is a
    *draft* until the user explicitly publishes it — so a failed analysis
    never reaches anyone's feed, and the user gets to tag and review first.
    """

    DRAFT = "draft"  # row created, waiting for the browser's upload to finish
    QUEUED = "queued"  # upload confirmed, message on SQS
    ANALYZING = "analyzing"  # worker picked it up
    ANALYZED = "analyzed"  # scored, awaiting user tagging + publish
    UNANALYZABLE = "unanalyzable"  # confidence gate rejected it (see failure_reason)
    PUBLISHED = "published"  # visible in feeds


def sa_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Build the SQLAlchemy column type for one of the StrEnums above.

    SQLAlchemy's Enum type defaults to sending the Python member's *name*
    ("DRAFT") to the database, not its .value ("draft") — even for a
    StrEnum. Every native Postgres enum type here was created (via Alembic)
    with the lowercase values, so without values_callable every insert of a
    non-null enum column fails with "invalid input value for enum ...:
    DRAFT". Centralized here so the fix lives in one place instead of being
    repeated at every call site.
    """
    return SAEnum(
        enum_cls, name=name, native_enum=True, values_callable=lambda e: [m.value for m in e]
    )
