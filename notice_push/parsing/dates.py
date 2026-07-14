from __future__ import annotations

import re
from datetime import datetime
from typing import Optional


DATE_PATTERNS = (
    (r"(\d{4})\.(\d{1,2})\.(\d{1,2})", "%Y %m %d"),
    (r"(\d{4})-(\d{1,2})-(\d{1,2})", "%Y %m %d"),
    (r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{1,2}):(\d{1,2})", "%Y %m %d %H %M %S"),
    (r"(\d{4})/(\d{1,2})/(\d{1,2})", "%Y %m %d"),
    (r"(\d{4})年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s+(\d{1,2}):(\d{1,2})", "%Y %m %d %H %M"),
    (r"(\d{4})年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", "%Y %m %d"),
)


def parse_date(text: str) -> Optional[datetime]:
    if not text:
        return None
    for pattern, fmt in DATE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return datetime.strptime(" ".join(match.groups()), fmt)
    return None
