from __future__ import annotations

import unicodedata


def normalize_company_search_text(value: str) -> str:
    """Normalize search comparison text without altering a displayed legal name."""
    return unicodedata.normalize("NFKC", value).strip().replace("證", "証").casefold()
