"""The canonical read layer (#231, #130 10.2): which canonical fact rows count at an anchor."""
from __future__ import annotations

# A card statement balance (a dated ``credit_balance`` snapshot, #207) is the
# card's liability at an anchor when it is the newest one on or before the
# anchor's date and at most this many days older than it: about one statement
# cycle plus two weeks, so a monthly statement always reaches the next month-end.
# An older one is not carried forward: the card falls back to its transactions (D-52).
CARD_STATEMENT_MAX_AGE_DAYS = 45
