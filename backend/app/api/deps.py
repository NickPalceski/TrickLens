"""Shared FastAPI dependencies.

Step 2 adds get_current_user here (Cognito JWT validation).
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

DbSession = Annotated[AsyncSession, Depends(get_db)]
