"""Card fee lines every card parser recognises (#308).

A currency conversion or foreign transaction fee is a fee the card charges, not a purchase:
Citi prints "CCY CONVERSION FEE", other issuers "FOREIGN TRANSACTION FEE", "FX FEE",
"CROSS BORDER FEE" and the like. Classified as FEE so the card's fees-and-interest total
(#300) includes them. Synthetic examples only; matching is on the description text.
"""
from __future__ import annotations

import re

_CONVERSION_FEE_RE = re.compile(
    r"\b(CCY|CURRENCY|FOREIGN|FX|OVERSEAS|CROSS[- ]?BORDER|DCC)\b[^|]*?\b(CONVERSION\s+)?(FEE|CHARGE)S?\b",
    re.IGNORECASE,
)
CARD_FEE_CATEGORY = "CreditCard::Fee"


def is_conversion_fee(description: str | None) -> bool:
    """True for a currency conversion / foreign transaction fee line."""
    return bool(description) and bool(_CONVERSION_FEE_RE.search(str(description)))
