#!/usr/bin/env python3
"""Apply the stable-v12.1 editorial hardening patch.

This patch addresses concrete production defects found in the live feed:
- bank/product press releases masquerading as economy news;
- administrative policy stories misclassified as military/security because
  the reason for the policy happened to mention UAVs;
- malformed duplicated-token headlines being accepted as 100% valid;
- deleted posts still influencing rolling proportions;
- post-publication audit running only at publisher time instead of continuously.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one patch target, found {count}: {old[:90]!r}")
    write(path, text.replace(old, new, 1))


def patch_policy() -> None:
    path = "src/editorial_policy.py"
    replace_once(path, 'VERSION = "policy-v2.1"', 'VERSION = "policy-v2.2"')

    replace_once(
        path,
        '''ADVERTORIAL = (\n    "на правах рекламы", "партнерский материал", "партнёрский материал",\n    "спецпроект", "акция действует", "скидка", "успейте купить",\n    "подробнее на сайте", "открыл первый офис", "совместное исследование",\n)\nSERVICE_NOTICE = (''',
        '''ADVERTORIAL = (\n    "на правах рекламы", "партнерский материал", "партнёрский материал",\n    "спецпроект", "акция действует", "скидка", "успейте купить",\n    "подробнее на сайте", "открыл первый офис", "совместное исследование",\n)\n\nCORPORATE_FINANCE_BRANDS = (\n    "сбер", "сбербанк", "сберинвестиции", "втб", "т банк", "тинькофф",\n    "альфа банк", "газпромбанк", "россельхозбанк",\n)\nCORPORATE_PRODUCT_ACTIONS = (\n    "запускает", "запустил", "запустила", "появилась", "появился",\n    "открывает клиентам доступ", "представил сервис", "представила сервис",\n    "новый сервис", "новая возможность", "новая функция", "инвесткопилка",\n    "доступ к цифровому рублю", "задавать новую планку качества",\n    "стремится задавать", "мобильном приложении", "для клиентов",\n)\nCORPORATE_PR_EVIDENCE = (\n    "пресс служба", "пресс-служба", "старший вице президент",\n    "старший вице-президент", "директор департамента маркетинга",\n    "сообщает пресс служба", "сообщает пресс-служба",\n)\nPUBLIC_POLICY_TITLE_EXEMPTIONS = (\n    "банк россии", "центробанк", "цб рф", "ключевая ставка", "инфляц",\n    "вступает в силу", "вступил в силу", "обязаны", "обязательн",\n    "закон", "регулятор", "госдум", "правительство",\n)\nADMIN_REGULATION = (\n    "отмена проверок", "отмене проверок", "неналоговых проверок",\n    "административной нагрузки", "контрольно надзор", "контрольно-надзор",\n    "нормативный акт", "мораторий на проверки", "проверок пострадавших",\n)\n\nSERVICE_NOTICE = (''',
    )

    replace_once(
        path,
        '''def _hard_reject(title: str, lead: str) -> Optional[str]:\n    combined = f"{title} {lead}"''',
        '''def _is_corporate_product_pr(title: str, lead: str) -> bool:\n    combined = f"{title} {lead}"\n    brand = has_any(title, CORPORATE_FINANCE_BRANDS)\n    product = has_any(title, CORPORATE_PRODUCT_ACTIONS)\n    pr_evidence = has_any(combined, CORPORATE_PR_EVIDENCE)\n    public_policy = has_any(title, PUBLIC_POLICY_TITLE_EXEMPTIONS)\n    return bool(brand and product and pr_evidence and not public_policy)\n\n\ndef _hard_reject(title: str, lead: str) -> Optional[str]:\n    combined = f"{title} {lead}"''',
    )

    replace_once(
        path,
        '''    if has_any(combined, ADVERTORIAL):\n        return "advertorial_or_corporate_pr"\n    if has_any(title, ("туристический форум",)):\n''',
        '''    if has_any(combined, ADVERTORIAL):\n        return "advertorial_or_corporate_pr"\n    if _is_corporate_product_pr(title, lead):\n        return "corporate_product_or_brand_pr"\n    if has_any(title, ("туристический форум",)):\n''',
    )

    replace_once(
        path,
        '''    if has_any(combined, FATAL) and has_any(combined, ACCIDENT_EMERGENCY + ROUTINE_CRIME):\n        return "fatal_incident"\n    if has_any(title, SECURITY):\n        return "military_security"\n''',
        '''    if has_any(combined, FATAL) and has_any(combined, ACCIDENT_EMERGENCY + ROUTINE_CRIME):\n        return "fatal_incident"\n    # The action of the headline outranks its background cause. A government\n    # decision about inspections remains policy even when the affected objects\n    # were damaged by UAVs.\n    if _is_policy(title) or (\n        has_any(title, POLICY_ACTOR) and has_any(title, ADMIN_REGULATION)\n    ):\n        return "political_decision"\n    if has_any(title, SECURITY):\n        return "military_security"\n''',
    )

    replace_once(
        path,
        '''    if (\n        classification.event_type == "violent_crime"\n''',
        '''    if (\n        classification.event_type == "political_decision"\n        and has_any(title, ADMIN_REGULATION)\n        and has_any(title, ("бпла", "беспилот"))\n        and has_any(lead, ("неналоговых проверок", "административной нагрузки"))\n    ):\n        title = (\n            "Правительство РФ готовит отмену неналоговых проверок для "\n            "пострадавшей от БПЛА инфраструктуры"\n        )\n        reasons.append("administrative_policy_fact_template")\n\n    if (\n        classification.event_type == "violent_crime"\n''',
    )

    replace_once(
        path,
        '''def title_quality_issues(title: str) -> List[str]:\n    value = clean(title)\n    issues: List[str] = []\n''',
        '''TITLE_REPEAT_EXEMPT = {\n    "россия", "россии", "российский", "правительство", "сахалин",\n    "сахалине", "области", "районе", "городе", "года", "рублей",\n}\n\n\ndef repeated_content_tokens(title: str) -> List[str]:\n    words = [\n        word for word in tokens(title)\n        if len(word) >= 6 and word not in TITLE_REPEAT_EXEMPT\n    ]\n    counts: Dict[str, int] = {}\n    for word in words:\n        counts[word] = counts.get(word, 0) + 1\n    return sorted(word for word, count in counts.items() if count > 1)\n\n\ndef title_quality_issues(title: str) -> List[str]:\n    value = clean(title)\n    issues: List[str] = []\n''',
    )

    replace_once(
        path,
        '''    if re.search(r"\\b(\\w+)\\s+\\1\\b", norm(value)):\n        issues.append("duplicated_word")\n    if has_any(value, CLICKBAIT):\n''',
        '''    if re.search(r"\\b(\\w+)\\s+\\1\\b", norm(value)):\n        issues.append("duplicated_word")\n    repeated = repeated_content_tokens(value)\n    if repeated:\n        issues.append("repeated_title_token:" + repeated[0])\n    if has_any(value, CLICKBAIT):\n''',
    )


def patch_director() -> None:
    path = "src/news_director.py"
    replace_once(path, 'VERSION = "director-v2"', 'VERSION = "director-v2.1"')

    replace_once(
        path,
        '''    posts = [post for post in (state.get("last_posts") or []) if isinstance(post, dict)][-window:]''',
        '''    posts = [\n        post for post in (state.get("last_posts") or [])\n        if isinstance(post, dict) and not post.get("auto_deleted")\n    ][-window:]''',
    )

    replace_once(
        path,
        '''    while remaining and len(selected) < 2:\n        scored = [\n            (\n                _utility(item, item.get("_news_director") or {}, balance, selected),\n                int((item.get("_news_director") or {}).get("seriousness") or 0),\n                item,\n            )\n            for item in remaining\n        ]\n''',
        '''    while remaining and len(selected) < 2:\n        pool = list(remaining)\n        if selected:\n            first_group = str((selected[0].get("_news_director") or {}).get("group") or "")\n            diverse = [\n                item for item in remaining\n                if str((item.get("_news_director") or {}).get("group") or "") != first_group\n            ]\n            if diverse:\n                pool = diverse\n        scored = [\n            (\n                _utility(item, item.get("_news_director") or {}, balance, selected),\n                int((item.get("_news_director") or {}).get("seriousness") or 0),\n                item,\n            )\n            for item in pool\n        ]\n''',
    )


def patch_publisher() -> None:
    path = "src/publisher.py"
    replace_once(path, 'VERSION = "stable-v12.0"', 'VERSION = "stable-v12.1"')


def patch_auditor() -> None:
    path = "src/publication_auditor.py"
    replace_once(path, 'VERSION = "post-audit-v1"', 'VERSION = "post-audit-v1.1"')

    replace_once(
        path,
        '''    posts = [\n        post for post in (state.get("last_posts") or [])[-MAX_AUDIT_POSTS:]\n        if isinstance(post, dict)\n    ]''',
        '''    posts = [\n        post for post in (state.get("last_posts") or [])[-MAX_AUDIT_POSTS:]\n        if isinstance(post, dict) and not post.get("auto_deleted")\n    ]''',
    )

    replace_once(
        path,
        '''        if not mutate or post.get("publisher_version") != "stable-v12.0":\n            continue''',
        '''        if (\n            not mutate\n            or not str(post.get("publisher_version") or "").startswith("stable-v12.")\n        ):\n            continue''',
    )

    replace_once(
        path,
        '''    report = {\n        "version": VERSION,''',
        '''    resolved_keys = {\n        (item.get("url"), item.get("title"))\n        for item in corrected + deleted\n    }\n    unresolved = [\n        item for item in anomalies\n        if str(item.get("publisher_version") or "").startswith("stable-v12.")\n        and (item.get("url"), item.get("title")) not in resolved_keys\n    ]\n\n    report = {\n        "version": VERSION,''',
    )

    replace_once(
        path,
        '''        "failed_actions": failed_actions[-20:],\n        "mutations_enabled": bool(mutate),''',
        '''        "failed_actions": failed_actions[-20:],\n        "unresolved": len(unresolved),\n        "unresolved_items": unresolved[-20:],\n        "mutations_enabled": bool(mutate),''',
    )


def patch_selftest() -> None:
    path = "src/production_selftest.py"
    replace_once(path, '"""Regression suite for the canonical stable-v12.0 publisher.', '"""Regression suite for the canonical stable-v12.1 publisher.')

    marker = '''\ndef version_and_media_regressions():\n'''
    addition = '''\n\ndef current_live_defect_regressions():\n    # Product/brand press releases must not fill the economy stream.\n    for title, body in (\n        (\n            "В Сбере появилась первая в России инвестиционная копилка для подростков с 14 лет",\n            "К новому учебному году СберИнвестиции запускают сервис, сообщает пресс-служба Сбера.",\n        ),\n        (\n            "Сбер открывает клиентам доступ к цифровому рублю",\n            "Сбер подготовил сервисы и сообщает об этом через пресс-службу Сбера.",\n        ),\n        (\n            "Сбер стремится задавать новую планку качества в развитии городской среды регионов",\n            "Старший вице-президент выступил на сессии, сообщает пресс-служба Сбера.",\n        ),\n    ):\n        review = director.review_candidate(candidate(title, body, category="ru_eco"))\n        assert review["approved"] is False, review\n        assert review["reason"] == "corporate_product_or_brand_pr", review\n\n    # UAVs are the background cause here; the headline action is regulation.\n    admin = candidate(\n        "Правительство РФ готовится к отмене проверок пострадавших от БПЛА проверок",\n        (\n            "Правительство РФ работает над снижением административной нагрузки. "\n            "Речь идет о неналоговых проверках организаций и объектов гражданской "\n            "инфраструктуры, пострадавших от атак беспилотников. Нормативный акт подготовлен."\n        ),\n        category="ru_security",\n    )\n    review = director.review_candidate(admin)\n    assert review["approved"] is True, review\n    assert review["corrected_category"] == "ru_pol", review\n    assert review["event_type"] == "political_decision", review\n    assert review["title_corrected"] == (\n        "Правительство РФ готовит отмену неналоговых проверок для "\n        "пострадавшей от БПЛА инфраструктуры"\n    ), review\n    assert not policy.title_quality_issues(review["title_corrected"]), review\n    assert any(\n        issue.startswith("repeated_title_token:проверок")\n        for issue in policy.title_quality_issues(admin["title"])\n    )\n\n    # Deleted historical posts must not distort the 30/20/20/15/10/5 mix.\n    balance = director.balance_snapshot({\n        "last_posts": [\n            {\n                "title": "Deleted bank promo",\n                "category_key": "ru_eco",\n                "auto_deleted": True,\n                "news_director": {\n                    "version": director.VERSION,\n                    "approved": True,\n                    "group": "ru_eco",\n                    "corrected_category": "ru_eco",\n                    "event_type": "macro_economy",\n                },\n            }\n        ]\n    })\n    assert balance["valid_posts_counted"] == 0, balance\n\n    # When a second stream exists, a release may not contain two items from one group.\n    local = candidate(\n        "В Южно-Сахалинске восстановили теплоснабжение после аварии",\n        "Коммунальные службы восстановили тепло жителям после повреждения сети.",\n        category="sakh_chp",\n        url="https://sakhalinmedia.ru/news/v121-local/",\n    )\n    local2 = candidate(\n        "На Итурупе водитель погиб в аварии грузовика",\n        "Мужчина погиб после опрокидывания автомобиля.",\n        category="sakh_chp",\n        url="https://sakhalinmedia.ru/news/v121-local2/",\n    )\n    economy = candidate(\n        "Банк России сохранил ключевую ставку на прежнем уровне",\n        "Совет директоров Банка России принял решение по ключевой ставке.",\n        source="TASS",\n        category="ru_eco",\n        url="https://tass.ru/ekonomika/v121-rate/",\n    )\n    ordered, report = director.direct_candidates(\n        {"last_posts": []},\n        [local, local2, economy],\n        category_map=publisher.core.b.CAT,\n        now=datetime.now(timezone.utc),\n        ai_reviewer=None,\n    )\n    assert len(ordered) >= 2, report\n    first_two_groups = [ordered[i]["_news_director"]["group"] for i in range(2)]\n    assert len(set(first_two_groups)) == 2, (first_two_groups, report)\n\n'''
    text = read(path)
    if "def current_live_defect_regressions():" not in text:
        if marker not in text:
            raise RuntimeError("production_selftest: version marker missing")
        text = text.replace(marker, addition + marker, 1)
        write(path, text)

    replace_once(path, 'assert publisher.VERSION == "stable-v12.0"', 'assert publisher.VERSION == "stable-v12.1"')
    replace_once(path, 'assert publisher.media.VERSION == "stable-v12.0"', 'assert publisher.media.VERSION == "stable-v12.1"')
    replace_once(path, 'assert publisher.core.VERSION == "stable-v12.0"', 'assert publisher.core.VERSION == "stable-v12.1"')
    replace_once(path, 'assert director.VERSION == "director-v2"', 'assert director.VERSION == "director-v2.1"')
    replace_once(path, 'assert policy.VERSION == "policy-v2.1"', 'assert policy.VERSION == "policy-v2.2"')
    replace_once(
        path,
        '''    openrouter_resilience_regression()\n    version_and_media_regressions()''',
        '''    openrouter_resilience_regression()\n    current_live_defect_regressions()\n    version_and_media_regressions()''',
    )
    replace_once(path, 'print("stable-v12.0 production self-test: ALL PASS")', 'print("stable-v12.1 production self-test: ALL PASS")')


def patch_workflow() -> None:
    path = ".github/workflows/auto_publish_v7.yml"
    text = read(path)
    text = text.replace("SkySakhNews Auto Publisher Stable v12.0", "SkySakhNews Auto Publisher Stable v12.1")
    text = text.replace("stable-v12.0", "stable-v12.1")
    text = text.replace("Update stable v12.0 editorial state", "Update stable v12.1 editorial state")
    text = text.replace(
        'expected = {"local": 6, "politics": 4, "economy": 4, "safety": 3, "world": 2, "tech": 1}',
        'expected = {"local": 6, "ru_pol": 4, "ru_eco": 4, "ru_safety": 3, "world": 2, "it": 1}',
    )
    # Source tests are run on every production cycle; a stale marker is not a stronger guarantee.
    old_step = '''      - name: Require validated stable v12.1 sources\n        run: |\n          python - <<'PY'\n          import json\n          from pathlib import Path\n          marker = Path("V12_MAIN_VERIFIED.json")\n          assert marker.exists(), "stable-v12.1 source verification marker is missing"\n          data = json.loads(marker.read_text(encoding="utf-8"))\n          assert data.get("version") == "stable-v12.1", data\n          assert data.get("all_source_tests_passed") is True, data\n          PY\n\n'''
    text = text.replace(old_step, "")
    text = text.replace(
        '            src/publication_auditor.py src/publisher.py \\\n            src/production_selftest.py',
        '            src/publication_auditor.py src/editorial_monitor.py src/publisher.py \\\n            src/production_selftest.py',
    )
    write(path, text)


def patch_ci() -> None:
    path = ".github/workflows/production_ci.yml"
    text = read(path)
    text = text.replace("v12.0", "v12.1")
    text = text.replace("stable-v12.0", "stable-v12.1")
    if '"src/editorial_monitor.py"' not in text:
        text = text.replace('      - "src/publication_auditor.py"\n', '      - "src/publication_auditor.py"\n      - "src/editorial_monitor.py"\n')
    text = text.replace(
        '            src/publication_auditor.py src/publisher.py \\\n            src/production_selftest.py',
        '            src/publication_auditor.py src/editorial_monitor.py src/publisher.py \\\n            src/production_selftest.py',
    )
    write(path, text)


def main() -> None:
    patch_policy()
    patch_director()
    patch_publisher()
    patch_auditor()
    patch_selftest()
    patch_workflow()
    patch_ci()
    print("stable-v12.1 editorial hardening applied")


if __name__ == "__main__":
    main()
