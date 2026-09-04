"""Regression suite for the canonical stable-v12.0 publisher.

The suite encodes the actual Telegram-feed failures reported by the user and
runs without Telegram or live-news network access before every production run.
"""

from __future__ import annotations

import copy
import os
from datetime import datetime, timedelta, timezone

import category_reconciler as reconciler
import editorial_gate as gate
import editorial_gate_runner as editorial
import editorial_policy as policy
import media_enforced_runner as media
import news_director as director
import publication_auditor
import publisher


def candidate(
    title: str,
    text: str,
    *,
    source: str = "SakhalinMedia.ru",
    url: str = "https://sakhalinmedia.ru/news/test/",
    category: str = "sakh",
    score: int = 100,
):
    return {
        "title": title,
        "source_text": text,
        "source": source,
        "url": url,
        "category_key": category,
        "category": category,
        "footer": category,
        "score": score,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "title_hash": "a" * 40,
        "topic_cluster": category + ":test",
    }


def assert_review(
    item,
    *,
    approved: bool,
    category: str | None = None,
    reason: str | None = None,
):
    review = director.review_candidate(item)
    assert review["approved"] is approved, (item["title"], review)
    if category is not None:
        assert review.get("corrected_category") == category, (item["title"], review)
    if reason is not None:
        assert review.get("reason") == reason, (item["title"], review)
    return review


def exact_feed_regressions():
    assert_review(
        candidate(
            "В Южно-Сахалинске наградили волонтёров Победы и поисковиков знаком Доброволец Сахалинской области",
            "В арт-резиденции состоялась торжественная церемония награждения.",
            url="https://sakhalinmedia.ru/news/2608836/",
        ),
        approved=False,
        reason="ceremony_or_congratulation",
    )

    assert_review(
        candidate(
            "В этот день, 3 сентября, в 1945 году Советская армия одержала победу над Японией",
            "Исторический материал напоминает о событиях 1945 года.",
            url="https://sakhalinmedia.ru/news/1155672/",
            category="geo",
        ),
        approved=False,
        reason="calendar_or_archive",
    )

    assert_review(
        candidate(
            "РусГидро открыло единый расчётно-информационный центр в Поронайске Сахалинской области",
            "Услугами центра смогут воспользоваться более 20 тысяч жителей Поронайского округа.",
            url="https://sakhalinmedia.ru/news/2608453/",
        ),
        approved=True,
        category="sakh",
    )

    vtb = candidate(
        "Прогноз ВТБ: рынок сбережений в 2026 году вырастет на 8%",
        "По прогнозам ВТБ, объём средств в российских банках достигнет 71 трлн рублей.",
        url="https://sakhalinmedia.ru/news/2608276/",
    )
    assert reconciler.suggest_category(vtb) == "ru_eco"
    assert_review(vtb, approved=True, category="ru_eco")

    assert_review(
        candidate(
            "Ветерана Вячеслава Гаврилова поздравили с Днем Победы над милитаристской Японией",
            "Глава города выразил ветерану благодарность.",
            source="Sakh.online",
            url="https://sakh.online/news/18/test",
            category="geo",
        ),
        approved=False,
        reason="ceremony_or_congratulation",
    )

    puppy = candidate(
        "Жительница Южно-Сахалинска лишилась денег при попытке купить щенка в интернете",
        "Полиция расследует дистанционное мошенничество.",
        url="https://sakhalinmedia.ru/news/2607890/",
    )
    puppy_review = assert_review(
        puppy,
        approved=False,
        category="sakh_chp",
        reason="importance_below_threshold",
    )
    assert puppy_review["event_type"] == "fraud", puppy_review

    assert_review(
        candidate(
            "Водитель Урала погиб при опрокидывании грузовика на Итурупе",
            "Грузовой автомобиль сошёл с проезжей части и опрокинулся в кювет.",
            url="https://sakhalinmedia.ru/news/2607800/",
        ),
        approved=True,
        category="sakh_chp",
    )

    assert_review(
        candidate(
            "Путин: российско-японские отношения ухудшились из-за позиции Токио",
            "Президент России заявил, что ответственность лежит на японском правительстве.",
            url="https://sakhalinmedia.ru/news/2607801/",
            category="geo",
        ),
        approved=True,
        category="geo",
    )

    traffic = assert_review(
        candidate(
            "Пять пьяных, 16 без прав: какие правила нарушили водители Сахалина за сутки",
            "Инспекторы ГАИ провели профилактический рейд и пресекли 126 нарушений ПДД.",
            url="https://sakhalinmedia.ru/news/2610302/",
        ),
        approved=False,
        category="sakh",
        reason="routine_traffic_statistics",
    )
    assert traffic["event_type"] == "traffic_enforcement", traffic

    assert_review(
        candidate(
            "Чекунков сообщил о включении программы газификации ДФО в генсхему до 2050 года",
            "Минвостокразвития, Минэнерго, регионы и Газпром определят инвестиции и финансирование.",
            source="TASS",
            url="https://tass.ru/ekonomika/1",
            category="ru_eco",
        ),
        approved=True,
        category="ru_eco",
    )


def service_notice_and_violent_crime_regressions():
    service = candidate(
        "Полиция на Сахалине ищет Александра Ледяева, чтобы вернуть ему вещи и документы",
        "Мужчину разыскивают, чтобы вернуть ему найденные вещи и документы.",
        source="ASTV",
        url="https://astv.ru/news/society/service-notice",
        category="sakh_chp",
    )
    assert_review(
        service,
        approved=False,
        reason="service_or_lost_and_found_notice",
    )

    murder = candidate(
        "Предъявили обвинение: сахалинца, который ранил и удерживал в сожительницу, взяли под стражу",
        (
            "Женщина скончалась в больнице. Мужчине предъявлено обвинение в убийстве "
            "и незаконном лишении свободы женщины. Суд избрал заключение под стражу."
        ),
        source="ASTV",
        url="https://astv.ru/news/criminal/murder-case",
        category="sakh",
    )
    review = assert_review(murder, approved=True, category="sakh_chp")
    assert review["event_type"] == "violent_crime", review
    assert review["title_corrected"] == (
        "Сахалинца заключили под стражу по обвинению в убийстве женщины"
    ), review
    assert "violent_crime_fact_template" in review["title_corrections"], review

    forum = candidate(
        "В Южно-Сахалинске открылся 3-й туристический форум «Маршрут построен»",
        "Участники обсудили туристические направления и культурную программу.",
        source="Sakh.online",
        url="https://sakh.online/news/forum",
    )
    assert_review(
        forum,
        approved=False,
        reason="routine_event_without_outcome",
    )


def scope_and_stream_regressions():
    world_ru = candidate(
        "China and Russia discuss sanctions and the future of bilateral relations",
        "The leaders discussed Russia, sanctions and bilateral relations.",
        source="BBC World",
        url="https://www.bbc.com/news/world-russia-test",
        category="geo",
    )
    assert_review(world_ru, approved=True, category="world_ru")

    generic_world = candidate(
        "China's CO2 emissions fall in the second quarter",
        "The report analyses changes in domestic industrial emissions.",
        source="Guardian World",
        url="https://www.theguardian.com/world/china-emissions-test",
        category="geo",
    )
    assert_review(
        generic_world,
        approved=False,
        reason="no_supported_news_stream",
    )

    it_story = candidate(
        "OpenAI представила новую модель искусственного интеллекта для разработчиков",
        "Компания объявила о выпуске модели и новых инструментах API.",
        source="BBC Technology",
        url="https://www.bbc.com/news/technology-openai-test",
        category="it",
    )
    assert_review(it_story, approved=True, category="it")

    policy_not_it = candidate(
        "Путин: особый правовой режим для обкатки технологий запустят с 1 января",
        "Президент России сообщил о государственном правовом режиме для новых решений.",
        source="SakhalinMedia.ru",
        url="https://sakhalinmedia.ru/news/legal-tech-regime/",
        category="it",
    )
    assert_review(policy_not_it, approved=True, category="ru_pol")

    smoke = candidate(
        "Дым от бушующих в Якутии пожаров дошёл до Курил",
        "Жители Северо-Курильска наблюдают завесу и ощущают запах гари.",
        source="ASTV",
        url="https://astv.ru/news/smoke-kurils",
        category="sakh_chp",
    )
    assert_review(smoke, approved=True, category="sakh_chp")


def boilerplate_and_language_regressions():
    dirty = (
        "Читайте последние актуальные новости главных событий Сахалина на тему X. "
        "ВТБ ожидает, что рынок сбережений России вырастет до 71 трлн рублей. "
        "ВТБ ожидает, что рынок сбережений России вырастет до 71 трлн рублей. "
        "Мы будем присылать вам на почту самые просматриваемые новости за день"
    )
    cleaned = policy.clean_article_text(dirty)
    assert cleaned.count("рынок сбережений") == 1, cleaned
    assert "присылать вам на почту" not in cleaned, cleaned

    assert "foreign" not in gate.infer_topics(
        "Не санаторий и не дача — пенсионеры нашли место у моря"
    )
    assert "foreign" in gate.infer_topics(
        "НАТО усиливает военное присутствие в Европе"
    )
    imoex_text = "Индекс Мосбиржи вырос на открытии торгов"
    imoex_topics = gate.infer_topics(imoex_text)
    imoex_matches = [
        marker for marker in policy.FOREIGN_MARKERS
        if policy.marker_match(imoex_text, marker)
    ]
    assert "foreign" not in imoex_topics, {
        "topics": sorted(imoex_topics), "matches": imoex_matches
    }


def exact_proportion_and_selection_regression():
    assert director.ROLLING_WINDOW == 20
    assert director.TARGET_COUNTS == {
        "local": 6,
        "ru_pol": 4,
        "ru_eco": 4,
        "ru_safety": 3,
        "world": 2,
        "it": 1,
    }
    assert sum(director.TARGET_COUNTS.values()) == 20

    last_posts = []
    groups = (
        ["local"] * 8
        + ["ru_pol"] * 4
        + ["ru_eco"] * 4
        + ["ru_safety"] * 3
        + ["it"]
    )
    category_for_group = {
        "local": "sakh",
        "ru_pol": "ru_pol",
        "ru_eco": "ru_eco",
        "ru_safety": "ru_incident",
        "world": "geo",
        "it": "it",
    }
    for index, group in enumerate(groups):
        last_posts.append({
            "title": f"Synthetic valid post {index}",
            "source": "Synthetic",
            "category_key": category_for_group[group],
            "news_director": {
                "version": director.VERSION,
                "approved": True,
                "group": group,
                "corrected_category": category_for_group[group],
                "event_type": "general",
                "subtype": "general",
            },
        })

    items = [
        candidate(
            "В Южно-Сахалинске восстановили теплоснабжение после аварии",
            "Коммунальные службы восстановили тепло для жителей города.",
            url="https://sakhalinmedia.ru/news/mix-local/",
            category="sakh_chp",
        ),
        candidate(
            "Russia and Britain discuss sanctions and diplomatic relations",
            "The governments discussed sanctions and Russia's relations with Britain.",
            source="BBC World",
            url="https://www.bbc.com/news/mix-world-1",
            category="world_ru",
        ),
        candidate(
            "US and Iran resume negotiations over a ceasefire agreement",
            "The United States and Iran resumed diplomatic talks.",
            source="Reuters",
            url="https://www.reuters.com/world/mix-world-2",
            category="geo",
        ),
    ]

    ordered, report = director.direct_candidates(
        {"last_posts": last_posts},
        items,
        category_map=publisher.core.b.CAT,
        now=datetime(2026, 9, 4, 19, 0, tzinfo=timezone(timedelta(hours=11))),
        ai_reviewer=None,
    )
    assert len(ordered) >= 2, report
    assert {item["category_key"] for item in ordered[:2]} == {"world_ru", "geo"}, report
    assert report["selected_groups"] == ["world", "world"], report


def source_diversity_regression():
    astv_one = candidate(
        "В Южно-Сахалинске после аварии восстановили теплоснабжение 30 домов",
        "Коммунальные службы устранили повреждение сети и вернули тепло жителям.",
        source="ASTV",
        url="https://astv.ru/news/source-diversity-1",
        category="sakh_chp",
    )
    astv_two = candidate(
        "На Сахалине пожарные эвакуировали жильцов многоэтажного дома",
        "Из здания эвакуировали жителей, пострадавших нет.",
        source="ASTV",
        url="https://astv.ru/news/source-diversity-2",
        category="sakh_chp",
    )
    interfax = candidate(
        "Правительство России утвердило программу развития транспорта",
        "Правительство утвердило государственную программу развития транспортной инфраструктуры.",
        source="Interfax",
        url="https://www.interfax.ru/russia/source-diversity-3",
        category="ru_pol",
    )

    ordered, report = director.direct_candidates(
        {"last_posts": []},
        [astv_one, astv_two, interfax],
        category_map=publisher.core.b.CAT,
        now=datetime.now(timezone(timedelta(hours=11))),
        ai_reviewer=None,
    )
    assert len(ordered) >= 2, report
    assert len({item["source"] for item in ordered[:2]}) == 2, report


def repetition_regression():
    prior = []
    for index in range(2):
        prior.append({
            "title": f"Сахалинец перевёл мошенникам {index + 1} миллион рублей",
            "source": "SakhalinMedia.ru",
            "category_key": "sakh_chp",
            "news_director": {
                "version": director.VERSION,
                "approved": True,
                "group": "local",
                "corrected_category": "sakh_chp",
                "event_type": "fraud",
                "subtype": "fraud",
            },
        })

    new_fraud = candidate(
        "Житель Южно-Сахалинска перевёл мошенникам 3 миллиона рублей",
        "Полиция расследует дистанционное мошенничество.",
        url="https://sakhalinmedia.ru/news/new-fraud/",
        category="sakh_chp",
    )
    strong_local = candidate(
        "После аварии в Южно-Сахалинске восстановили теплоснабжение 30 домов",
        "Коммунальные службы устранили повреждение сети.",
        url="https://sakhalinmedia.ru/news/heating/",
        category="sakh_chp",
    )

    ordered, report = director.direct_candidates(
        {"last_posts": prior},
        [new_fraud, strong_local],
        category_map=publisher.core.b.CAT,
        now=datetime.now(timezone(timedelta(hours=11))),
        ai_reviewer=None,
    )
    assert all(item["url"] != new_fraud["url"] for item in ordered), report
    assert report["by_url"][new_fraud["url"]]["reason"] == "event_quota_exhausted"


def final_contract_and_auditor_regressions():
    murder = candidate(
        "Предъявили обвинение: сахалинца, который ранил и удерживал в сожительницу, взяли под стражу",
        (
            "Женщина скончалась в больнице. Мужчине предъявлено обвинение в убийстве "
            "и незаконном лишении свободы женщины. Суд избрал заключение под стражу."
        ),
        source="ASTV",
        url="https://astv.ru/news/criminal/murder-contract",
        category="sakh",
    )
    review = director.review_candidate(murder)
    murder["title_original"] = murder["title"]
    murder["title"] = review["title_corrected"]
    murder["category_key"] = "sakh_chp"
    row = {
        "title_ru": review["title_corrected"],
        "body": [
            "Женщина скончалась в больнице.",
            "Мужчине предъявлено обвинение в убийстве и суд избрал заключение под стражу.",
        ],
        "editorial_mode": "extractive_fallback",
    }
    contract = director.validate_final(murder, row)
    assert contract["approved"] is True, contract

    state = {
        "last_posts": [{
            "title": "Полиция на Сахалине ищет владельца, чтобы вернуть документы",
            "source": "ASTV",
            "category_key": "sakh_chp",
            "url": "https://astv.ru/news/bad-v12-post",
            "source_text_excerpt": "Полиция хочет вернуть владельцу найденные документы.",
            "publisher_version": "stable-v12.0",
            "time_sakhalin": datetime.now(timezone(timedelta(hours=11))).isoformat(),
        }]
    }
    audit = publication_auditor.audit_recent_posts(
        state,
        category_map=publisher.core.b.CAT,
        render_caption=publisher.core.b.caption,
        mutate=False,
    )
    assert audit["checked"] == 1
    assert len(audit["anomalies"]) == 1, audit
    assert not audit["corrected"] and not audit["deleted"]


def openrouter_resilience_regression():
    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200
            self.text = ""
            self.headers = {}

        def json(self):
            return self._payload

    responses = [
        FakeResponse({"model": "free/empty", "choices": [{"message": {"content": ""}}]}),
        FakeResponse({"model": "free/invalid", "choices": [{"message": {"content": "not-json"}}]}),
        FakeResponse({"model": "free/valid", "choices": [{"message": {"content": '{"ok": true}'}}]}),
    ]
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    names = (
        "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENROUTER_FALLBACK_MODELS",
        "OPENROUTER_MAX_ATTEMPTS", "OPENROUTER_RETRY_BASE_SECONDS",
    )
    saved_env = {name: os.environ.get(name) for name in names}
    saved_post = editorial.core.b.requests.post
    saved_open = editorial._OPENROUTER_CIRCUIT_OPEN
    saved_reason = editorial._OPENROUTER_CIRCUIT_REASON

    try:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        os.environ["OPENROUTER_MODEL"] = ""
        os.environ["OPENROUTER_FALLBACK_MODELS"] = ""
        os.environ["OPENROUTER_MAX_ATTEMPTS"] = "3"
        os.environ["OPENROUTER_RETRY_BASE_SECONDS"] = "0"
        editorial._OPENROUTER_CIRCUIT_OPEN = False
        editorial._OPENROUTER_CIRCUIT_REASON = ""
        editorial.core.b.requests.post = fake_post
        raw = editorial.resilient_openrouter(
            [{"role": "user", "content": "Return JSON"}],
            max_tokens=128,
        )
        assert editorial.core.b.parse_obj(raw) == {"ok": True}
        assert len(calls) == 3
        assert all(call["json"]["response_format"] == {"type": "json_object"} for call in calls)
    finally:
        editorial.core.b.requests.post = saved_post
        editorial._OPENROUTER_CIRCUIT_OPEN = saved_open
        editorial._OPENROUTER_CIRCUIT_REASON = saved_reason
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def version_and_media_regressions():
    assert publisher.VERSION == "stable-v12.0"
    assert publisher.media.VERSION == "stable-v12.0"
    assert publisher.core.VERSION == "stable-v12.0"
    assert publisher.core.b.IMAGE_REQUIRED is True
    assert director.VERSION == "director-v2"
    assert policy.VERSION == "policy-v2.1"

    good_media = {
        "image": b"x" * 12000,
        "image_url": "https://sakhalinmedia.ru/f/big/news-photo.jpg",
        "image_hash": "f" * 40,
    }
    assert media._is_source_media(good_media)[0] is True
    assert media._is_source_media({})[0] is False


def main():
    exact_feed_regressions()
    service_notice_and_violent_crime_regressions()
    scope_and_stream_regressions()
    boilerplate_and_language_regressions()
    exact_proportion_and_selection_regression()
    source_diversity_regression()
    repetition_regression()
    final_contract_and_auditor_regressions()
    openrouter_resilience_regression()
    version_and_media_regressions()
    print("stable-v12.0 production self-test: ALL PASS")


if __name__ == "__main__":
    main()
