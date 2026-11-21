"""Transactional database-backed rate limiting.

Vercel runs many independent function instances, so in-memory counters
cannot enforce shared limits. Counters live in the rate_limits table and
are incremented with an atomic upsert inside their own short transaction,
so the same pseudonymous identity gets one authoritative count across
every instance. Identities are HMAC hashes; no raw IP is ever stored.
"""
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import RateLimit
from app.security import voter_hash


class RateLimitExceeded(HTTPException):
    def __init__(self, retry_after):
        super().__init__(429, "Too many requests. Please try again later.")
        self.retry_after = retry_after


def rate_limit(action, limit, period):
    """FastAPI dependency allowing `limit` requests per `period` seconds.

    Runs after CSRF validation and before endpoint input validation, so a
    rejected form still consumes a slot, matching the original behavior.
    The increment commits even when the endpoint later fails, on purpose.
    """
    def check(request: Request, db: Session = Depends(get_db)):
        now = int(time.time())
        window_start = now - (now % period)
        if db.bind.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as upsert
        else:
            from sqlalchemy.dialects.postgresql import insert as upsert
        statement = upsert(RateLimit).values(action=action,
            identity_hash=voter_hash(request), window_start=window_start, count=1)
        statement = statement.on_conflict_do_update(
            index_elements=["action", "identity_hash", "window_start"],
            set_={"count": RateLimit.count + 1}).returning(RateLimit.count)
        count = db.scalar(statement)
        # Expired windows of THIS action are worthless; drop them in the same
        # transaction. Scope by action: windows are period-aligned, so a short
        # window (admin sign-ins, one minute) would otherwise erase active
        # hourly counters, whose aligned start is earlier in wall-clock terms.
        db.execute(delete(RateLimit).where(RateLimit.action == action,
                                           RateLimit.window_start < window_start))
        db.commit()
        if count > limit:
            raise RateLimitExceeded(period)
    return check
