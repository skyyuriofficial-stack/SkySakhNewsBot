"""Compatibility adapter for the authoritative editorial policy.

All category decisions are delegated to :mod:`editorial_policy`. This prevents
three classifiers from assigning three different streams to the same story.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

import editorial_policy as policy

VERSION = "reconciler-v3"


def suggest_category(candidate: Mapping[str, Any]) -> Optional[str]:
    """Return the only supported final category, or ``None`` for rejection."""
    return policy.classify(candidate).category_key


def explain_category(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the full auditable policy decision for diagnostics and tests."""
    return policy.classify(candidate).to_dict()
