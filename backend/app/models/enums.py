"""Shared enums, mapped to native Postgres enum types.

Defined centrally so the API, the worker, and the database agree on the exact
same vocabulary.
"""

from enum import StrEnum


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
