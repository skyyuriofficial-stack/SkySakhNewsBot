#!/usr/bin/env python3
"""Fix the remaining stable-v12.1 publication-contract defects.

- no English headline can pass a Russian Telegram post;
- source-stage director may still evaluate legitimate foreign-language headlines;
- translated titles are grounded by exact source evidence instead of impossible
  cross-language token overlap;
- final autocorrection may never replace a valid Russian translation with the
  English source title;
- decimal comma/dot equivalence is respected by the invented-number guard;
- IT posts may contain legitimate Latin brand names without being rejected.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def write(path, text):
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path, old, new):
    text = read(path)
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one target, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def patch_v8_numbers():
    replace_once(
        "src/news_bot_v8.py",
        'def nums(text): return set(re.findall(r"\\d+(?:[,.]\\d+)?", text or ""))',
        'def nums(text): return {value.replace(",", ".") for value in re.findall(r"\\d+(?:[,.]\\d+)?", text or "")}',
    )


def patch_production_it_latin():
    replace_once(
        "src/production.py",
        '''    if core.b.ratio_latin(joined) > 0.10:\n        errors.append("latin_ratio_high")''',
        '''    # IT headlines legitimately retain brand/product names such as Nvidia,\n    # Hugging Face, OpenAI and ChatGPT. The prose must still be predominantly\n    # Russian, but those proper names are not translation failures.\n    latin_limit = 0.28 if c.get("category_key") == "it" else 0.10\n    if core.b.ratio_latin(joined) > latin_limit:\n        errors.append("latin_ratio_high")''',
    )


def patch_policy():
    path = "src/editorial_policy.py"
    replace_once(path, 'VERSION = "policy-v2.2"', 'VERSION = "policy-v2.3"')

    replace_once(
        path,
        '''def title_quality_issues(title: str) -> List[str]:\n    value = clean(title)\n    issues: List[str] = []''',
        '''def headline_is_russian(title: str) -> bool:\n    value = str(title or "")\n    cyr = len(re.findall(r"[А-Яа-яЁё]", value))\n    latin = len(re.findall(r"[A-Za-z]", value))\n    letters = cyr + latin\n    if cyr < 8 or letters == 0:\n        return False\n    # Allow Latin brand names in IT/economy titles while requiring the actual\n    # headline grammar to be Russian.\n    return cyr / letters >= 0.52\n\n\ndef _evidence_norm(value: Any) -> str:\n    return re.sub(r"\\s+", " ", norm(value)).strip()\n\n\ndef evidence_present(source: str, evidence: Any) -> bool:\n    ev = _evidence_norm(evidence)\n    src = _evidence_norm(source)\n    if not ev or len(ev.split()) < 4:\n        return False\n    if ev in src:\n        return True\n    ev_tokens = ev.split()\n    src_tokens = src.split()\n    if len(ev_tokens) < 5:\n        return False\n    target = set(ev_tokens)\n    window = len(ev_tokens) + 4\n    best = 0.0\n    for start in range(max(1, len(src_tokens) - window + 1)):\n        chunk = set(src_tokens[start:start + window])\n        best = max(best, len(target & chunk) / max(1, len(target)))\n    return best >= 0.90\n\n\ndef title_quality_issues(title: str) -> List[str]:\n    value = clean(title)\n    issues: List[str] = []''',
    )

    replace_once(
        path,
        '''    if len(value) > 180:\n        issues.append("title_too_long")\n    if SOURCE_SUFFIX_RE.search(value):''',
        '''    if len(value) > 180:\n        issues.append("title_too_long")\n    if not headline_is_russian(value):\n        issues.append("title_not_russian")\n    if SOURCE_SUFFIX_RE.search(value):''',
    )

    replace_once(
        path,
        '''    title_score, title_precision, title_coverage = gate.title_source_metrics(\n        source_title,\n        source_text,\n        final_title,\n    )\n\n    issues = list(title_issues)\n    if final_class.hard_reject_reason:\n        issues.append("final_hard_reject:" + final_class.hard_reject_reason)\n    if final_class.category_key != expected:\n        issues.append(f"final_category_mismatch:{final_class.category_key}->{expected}")\n    if title_score < 78 or title_precision < 78 or title_coverage < 50:\n        issues.append("final_title_not_grounded")''',
        '''    source_is_russian = gate.is_russian_text(source_title + " " + source_text)\n    foreign_evidence_ok = False\n    if source_is_russian:\n        title_score, title_precision, title_coverage = gate.title_source_metrics(\n            source_title, source_text, final_title\n        )\n    else:\n        # Cross-language token overlap is meaningless. Ground a translated\n        # headline/body through the exact source fragments carried by the draft.\n        full_source = f"{source_title} {source_text}"\n        title_evidence_ok = evidence_present(full_source, row.get("title_evidence"))\n        body = row.get("body") if isinstance(row.get("body"), list) else []\n        body_evidence = (\n            row.get("body_evidence")\n            if isinstance(row.get("body_evidence"), list)\n            else []\n        )\n        body_evidence_ok = (\n            len(body) >= 2\n            and len(body) == len(body_evidence)\n            and all(evidence_present(full_source, value) for value in body_evidence)\n        )\n        foreign_evidence_ok = bool(\n            headline_is_russian(final_title)\n            and title_evidence_ok\n            and body_evidence_ok\n        )\n        title_score = title_precision = title_coverage = 100 if foreign_evidence_ok else 0\n\n    issues = list(title_issues)\n    if final_class.hard_reject_reason:\n        issues.append("final_hard_reject:" + final_class.hard_reject_reason)\n    if final_class.category_key != expected:\n        issues.append(f"final_category_mismatch:{final_class.category_key}->{expected}")\n    if source_is_russian:\n        if title_score < 78 or title_precision < 78 or title_coverage < 50:\n            issues.append("final_title_not_grounded")\n    elif not foreign_evidence_ok:\n        issues.append("foreign_translation_evidence_missing")''',
    )

    replace_once(
        path,
        '''        "title_coverage": title_coverage,\n        "issues": issues,''',
        '''        "title_coverage": title_coverage,\n        "source_is_russian": source_is_russian,\n        "foreign_evidence_ok": foreign_evidence_ok,\n        "issues": issues,''',
    )


def patch_director_source_stage():
    path = "src/news_director.py"
    replace_once(
        path,
        '''    corrected_title, corrections = policy.autocorrect_title(candidate, classification)\n    title_issues = policy.title_quality_issues(corrected_title)\n    if title_issues and classification.event_type not in {"traffic_enforcement"}:''',
        '''    corrected_title, corrections = policy.autocorrect_title(candidate, classification)\n    title_issues = policy.title_quality_issues(corrected_title)\n    # The director reviews the source headline before translation. A legitimate\n    # foreign-language headline stays eligible here; the final publication\n    # contract later requires the Telegram headline itself to be Russian.\n    if not policy.headline_is_russian(corrected_title):\n        title_issues = [issue for issue in title_issues if issue != "title_not_russian"]\n    if title_issues and classification.event_type not in {"traffic_enforcement"}:''',
    )


def patch_publisher():
    path = "src/publisher.py"
    replace_once(
        path,
        '''def _attempt_final_autocorrection(candidate, row):\n    metadata = candidate.get("_news_director") or {}\n    corrected_title = str(metadata.get("title_corrected") or candidate.get("title") or "")\n\n    title_repaired = copy.deepcopy(row)\n    title_repaired["title_ru"] = corrected_title\n    title_repaired = _refresh_editorial_gate(candidate, title_repaired) or title_repaired\n    contract = director.validate_final(candidate, title_repaired)\n    if contract.get("approved"):\n        core.b.STATS["director_final_autocorrected"] += 1\n        return title_repaired, contract, "corrected_title"\n\n    fallback = prod._extractive_fallback(candidate)\n    if fallback:\n        fallback["title_ru"] = corrected_title\n        fallback = _refresh_editorial_gate(candidate, fallback) or fallback\n        contract = director.validate_final(candidate, fallback)\n        if contract.get("approved"):\n            core.b.STATS["director_final_autocorrected"] += 1\n            return fallback, contract, "safe_extractive_rebuild"\n\n    return None, contract, None''',
        '''def _attempt_final_autocorrection(candidate, row):\n    metadata = candidate.get("_news_director") or {}\n    source_title = str(metadata.get("title_corrected") or candidate.get("title") or "")\n    generated_title = str(row.get("title_ru") or "")\n\n    # Critical invariant: a foreign source title may never overwrite an already\n    # Russian translated headline. If neither candidate is Russian, fail closed.\n    if director.policy.headline_is_russian(generated_title):\n        corrected_title = generated_title\n    elif director.policy.headline_is_russian(source_title):\n        corrected_title = source_title\n    else:\n        contract = director.validate_final(candidate, row)\n        return None, contract, None\n\n    title_repaired = copy.deepcopy(row)\n    title_repaired["title_ru"] = corrected_title\n    title_repaired = _refresh_editorial_gate(candidate, title_repaired) or title_repaired\n    contract = director.validate_final(candidate, title_repaired)\n    if contract.get("approved"):\n        core.b.STATS["director_final_autocorrected"] += 1\n        return title_repaired, contract, "corrected_title"\n\n    # Extractive rebuild is valid only for a Russian source.\n    if gate_is_russian_source(candidate):\n        fallback = prod._extractive_fallback(candidate)\n        if fallback:\n            fallback["title_ru"] = corrected_title\n            fallback = _refresh_editorial_gate(candidate, fallback) or fallback\n            contract = director.validate_final(candidate, fallback)\n            if contract.get("approved"):\n                core.b.STATS["director_final_autocorrected"] += 1\n                return fallback, contract, "safe_extractive_rebuild"\n\n    return None, contract, None\n\n\ndef gate_is_russian_source(candidate):\n    return media.editorial.gate.is_russian_text(\n        str(candidate.get("title") or "")\n        + " "\n        + str(candidate.get("source_text") or "")\n    )''',
    )


def patch_tests():
    path = "src/production_selftest.py"
    text = read(path)
    marker = '''\ndef current_live_defect_regressions():\n'''
    tests = r'''

def final_russian_title_and_it_regressions():
    assert policy.headline_is_russian(
        "Nvidia покупает AI-платформу Hugging Face за 12,9 млрд долларов"
    )
    assert not policy.headline_is_russian(
        "Russian drone hits Ukrainian security headquarters, Zelensky says"
    )

    assert publisher.core.b.nums("$12.9bn") == publisher.core.b.nums("12,9 млрд") == {"12.9"}

    it_candidate = candidate(
        "Nvidia strikes $12.9bn deal to buy AI platform Hugging Face",
        "Nvidia agreed a $12.9bn deal to buy AI platform Hugging Face. The companies announced the transaction on Friday.",
        source="Guardian Technology",
        url="https://www.theguardian.com/technology/test-nvidia",
        category="it",
    )
    it_row = {
        "reject": False,
        "title_ru": "Nvidia покупает AI-платформу Hugging Face за 12,9 млрд долларов",
        "title_evidence": "Nvidia strikes $12.9bn deal to buy AI platform Hugging Face",
        "body": [
            "Nvidia договорилась купить платформу искусственного интеллекта Hugging Face за 12,9 млрд долларов.",
            "Компании объявили о сделке в пятницу; условия основаны на опубликованной информации источника.",
        ],
        "body_evidence": [
            "Nvidia agreed a $12.9bn deal to buy AI platform Hugging Face",
            "The companies announced the transaction on Friday",
        ],
        "footer": it_candidate["footer"],
    }
    generated_errors = publisher.prod._validate_generated_v99(it_row, it_candidate)
    assert "latin_ratio_high" not in generated_errors, generated_errors
    assert not any(error.startswith("invented_numbers:") for error in generated_errors), generated_errors

    world = candidate(
        "Russian drone hits Ukrainian security headquarters, Zelensky says",
        (
            "A Russian drone has hit the headquarters of the Security Service of Ukraine in Kyiv, "
            "Ukrainian President Volodymyr Zelensky has said. Officials said the building was damaged."
        ),
        source="BBC World",
        url="https://www.bbc.com/news/test-final-title",
        category="world_ru",
    )
    world["category"] = "🌍 Мир о России"
    world["footer"] = "МИР О РОССИИ"
    row = {
        "reject": False,
        "title_ru": "Российский дрон ударил по штаб-квартире СБУ в Киеве, заявил Зеленский",
        "title_evidence": "Russian drone hits Ukrainian security headquarters, Zelensky says",
        "body": [
            "Президент Украины Владимир Зеленский заявил, что российский беспилотник ударил по штаб-квартире СБУ в Киеве.",
            "По словам официальных лиц, здание было повреждено в результате атаки.",
        ],
        "body_evidence": [
            "A Russian drone has hit the headquarters of the Security Service of Ukraine in Kyiv",
            "Officials said the building was damaged",
        ],
        "footer": world["footer"],
        "editorial_gate": {
            "approved": True,
            "title_matches_source": 100,
            "category_matches_story": 100,
            "facts_supported": True,
            "meaning_changed": False,
        },
    }
    contract = policy.final_contract(world, row)
    assert contract["approved"] is True, contract
    assert contract["foreign_evidence_ok"] is True, contract

    bad = dict(row)
    bad["title_ru"] = world["title"]
    bad_contract = policy.final_contract(world, bad)
    assert bad_contract["approved"] is False, bad_contract
    assert "title_not_russian" in bad_contract["issues"], bad_contract

    world["_news_director"] = {
        "approved": True,
        "title_corrected": world["title"],
        "corrected_category": "world_ru",
        "group": "world",
        "event_type": "military_security",
        "seriousness": 95,
        "threshold": 78,
    }
    original_refresh = publisher._refresh_editorial_gate
    try:
        publisher._refresh_editorial_gate = lambda _candidate, draft: draft
        repaired, repaired_contract, _mode = publisher._attempt_final_autocorrection(world, row)
    finally:
        publisher._refresh_editorial_gate = original_refresh
    assert repaired is not None, repaired_contract
    assert repaired["title_ru"] == row["title_ru"], repaired
    assert policy.headline_is_russian(repaired["title_ru"]), repaired

'''
    if "def final_russian_title_and_it_regressions():" not in text:
        if marker not in text:
            raise RuntimeError("selftest insertion marker missing")
        text = text.replace(marker, tests + marker, 1)
    text = text.replace(
        '''    ai_translation_and_scope_regressions()\n    current_live_defect_regressions()''',
        '''    ai_translation_and_scope_regressions()\n    final_russian_title_and_it_regressions()\n    current_live_defect_regressions()''',
        1,
    )
    write(path, text)


def main():
    patch_v8_numbers()
    patch_production_it_latin()
    patch_policy()
    patch_director_source_stage()
    patch_publisher()
    patch_tests()
    print("final Russian-title and IT validation hardening applied")


if __name__ == "__main__":
    main()
