"""What a request gives a valuation call, for callers outside a request (#395).

Inside a request the user's home timezone is bound once the user is known
(``app.core.clock.bind_request_timezone``) and ``ValuationCacheMiddleware`` opens a
request scope, so "now" is frozen for the whole response (#147). A direct call (a
background job, a script, a test) gets neither: it runs in the app timezone and may
read "now" more than once. For a closed month that makes no difference, but the open
month is "now" in the user's timezone, so a user in New York and the app in Singapore
can be in different months at the same instant. ``valuation_context`` sets both, so a
direct call gives exactly what the API returns.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from app.core.clock import use_timezone
from app.services.user_preferences import effective_timezone
from app.valuation_cache import RequestScope, request_scope


@contextmanager
def valuation_context(db: Session, user_id: int) -> Iterator[RequestScope]:
    """Run a block as a request for ``user_id`` would: their timezone, one request scope."""
    with use_timezone(effective_timezone(db, user_id)), request_scope() as scope:
        yield scope
