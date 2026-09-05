#!/usr/bin/env python3
"""Compatibility wrapper for the v12.1 patcher against current main."""

import apply_editorial_v121 as base


def patch_director() -> None:
    path = "src/news_director.py"
    base.replace_once(path, 'VERSION = "director-v2"', 'VERSION = "director-v2.1"')

    base.replace_once(
        path,
        '''    posts = [post for post in (state.get("last_posts") or []) if isinstance(post, dict)][-window:]''',
        '''    posts = [\n        post for post in (state.get("last_posts") or [])\n        if isinstance(post, dict) and not post.get("auto_deleted")\n    ][-window:]''',
    )

    base.replace_once(
        path,
        '''    while remaining and len(selected) < 2:\n        candidate_pool = remaining\n        if selected:\n            selected_sources = {\n                _norm(item.get("source")) for item in selected\n            }\n            source_diverse = [\n                item for item in remaining\n                if _norm(item.get("source")) not in selected_sources\n            ]\n            # A two-post release from the same publisher looks like a reposted\n            # feed rather than an edited channel. Use another publisher when\n            # any fully approved alternative exists; only relax this when the\n            # entire qualified pool comes from one source.\n            if source_diverse:\n                candidate_pool = source_diverse\n\n        scored = [\n            (\n                _utility(item, item.get("_news_director") or {}, balance, selected),\n                int((item.get("_news_director") or {}).get("seriousness") or 0),\n                item,\n            )\n            for item in candidate_pool\n        ]\n''',
        '''    while remaining and len(selected) < 2:\n        candidate_pool = list(remaining)\n        if selected:\n            first_group = str(\n                (selected[0].get("_news_director") or {}).get("group") or ""\n            )\n            group_diverse = [\n                item for item in remaining\n                if str((item.get("_news_director") or {}).get("group") or "")\n                != first_group\n            ]\n            if group_diverse:\n                candidate_pool = group_diverse\n\n            selected_sources = {\n                _norm(item.get("source")) for item in selected\n            }\n            source_diverse = [\n                item for item in candidate_pool\n                if _norm(item.get("source")) not in selected_sources\n            ]\n            if source_diverse:\n                candidate_pool = source_diverse\n\n        scored = [\n            (\n                _utility(item, item.get("_news_director") or {}, balance, selected),\n                int((item.get("_news_director") or {}).get("seriousness") or 0),\n                item,\n            )\n            for item in candidate_pool\n        ]\n''',
    )


base.patch_director = patch_director
base.main()
