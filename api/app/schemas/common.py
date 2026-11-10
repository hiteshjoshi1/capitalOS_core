"""Shared field types for response models (#361).

Routes that return DB rows used to be encoded by FastAPI's ``jsonable_encoder``, which writes a
datetime with ``isoformat()`` ("...+00:00"). Pydantic's own JSON writes UTC as "Z". ``IsoDateTime``
keeps the old spelling, so adding a ``response_model`` doesn't change a byte of those timestamps.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Union
from uuid import UUID

from pydantic import PlainSerializer

IsoDateTime = Annotated[datetime, PlainSerializer(lambda v: v.isoformat(), return_type=str, when_used="json")]

# A wallet id: a UUID from the database, or the string the route already made of it.
WalletId = Union[UUID, str]
