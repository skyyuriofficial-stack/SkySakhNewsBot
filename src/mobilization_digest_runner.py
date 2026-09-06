from __future__ import annotations

import re
import time
from datetime import datetime

import mobilization_digest as digest

_original_openrouter = digest.openrouter
_original_validate = digest.validate_draft


def resilient_openrouter(messages, max_tokens=2400):
    last_error = None
    for attempt in range(3):
        try:
            text = _original_openrouter(messages, max_tokens=max_tokens)
            if text and text.strip():
                return text
            last_error = RuntimeError("empty OpenRouter content")
        except Exception as exc:
            last_error = exc
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"OpenRouter failed after retries: {last_error}")


def date_aware_validate(draft, evidence):
    issues = _original_validate(draft, evidence)
    date_numbers = set()
    for item in evidence:
        date_numbers.update(re.findall(r"\b\d+(?:[,.]\d+)?\b", str(item.get("published_utc") or "")))
    now = datetime.now(digest.TZ)
    date_numbers.update({str(now.day), str(now.month), str(now.year)})

    fixed = []
    for issue in issues:
        if not str(issue).startswith("invented_numbers:"):
            fixed.append(issue)
            continue
        raw = str(issue).split(":", 1)[1]
        values = {part for part in raw.split(",") if part}
        unsupported = values - date_numbers
        if unsupported:
            fixed.append("invented_numbers:" + ",".join(sorted(unsupported)))
    return fixed


digest.openrouter = resilient_openrouter
digest.validate_draft = date_aware_validate


if __name__ == "__main__":
    raise SystemExit(digest.main())
