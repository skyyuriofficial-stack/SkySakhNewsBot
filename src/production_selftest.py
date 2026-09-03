"""Regression suite for the canonical stable-v11.0 publisher.

The tests encode the real publication failures reported from the Telegram
channel. They run before every production cycle and in CI, without network or
Telegram access.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import category_reconciler as reconciler
import editorial_gate as gate
import editorial_gate_runner as editorial
import media_enforced_runner as media
import news_director as director
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


def screenshot_regressions():
    # 1. Ceremonial local content is not a release-worthy news item.
    assert_review(
        candidate(
            "В Южно-Сахалинске наградили волонтёров Победы и поисковиков знаком Доброволец Сахалинской области",
            "В арт-резиденции Маяк состоялась торжественная церемония награждения.",
            url="https://sakhalinmedia.ru/news/2608836/",
        ),
        approved=False,
        reason="ceremony_or_congratulation_low_value",
    )

    # 2. Calendar/history articles must not become current geopolitics.
    assert_review(
        candidate(
            "В этот день, 3 сентября, в 1945 году Советская армия одержала победу над Японией",
            "Материал напоминает о событиях 1945 года.",
            url="https://sakhalinmedia.ru/news/1155672/",
            category="geo",
        ),
        approved=False,
        reason="calendar_or_archive_not_current_news",
    )

    # 3. Significant local infrastructure remains in the Sakhalin stream.
    assert_review(
        candidate(
            "РусГидро открыло единый расчётно-информационный центр в Поронайске Сахалинской области",
            "Услугами центра смогут воспользоваться более 20 тысяч жителей Поронайского муниципального округа.",
            url="https://sakhalinmedia.ru/news/2608453/",
        ),
        approved=True,
        category="sakh",
    )

    # 4. Syndicated national economy is corrected from Sakhalin to Russia/economy.
    vtb = candidate(
        "Прогноз ВТБ: рынок сбережений в 2026 году вырастет на 8%",
        "По прогнозам ВТБ, объем средств в российских банках достигнет 71 трлн рублей.",
        url="https://sakhalinmedia.ru/news/2608276/",
    )
    assert reconciler.suggest_category(vtb) == "ru_eco"
    assert_review(vtb, approved=True, category="ru_eco")

    # 5. A congratulation to a veteran is a ceremony, not geopolitics.
    assert_review(
        candidate(
            "Ветерана Вячеслава Гаврилова поздравили с Днем Победы над милитаристской Японией",
            "Глава города выразил ветерану благодарность.",
            source="Sakh.online",
            url="https://sakh.online/news/18/test",
            category="geo",
        ),
        approved=False,
        reason="ceremony_or_congratulation_low_value",
    )

    # 6. Local online fraud is a Sakhalin incident, not generic local news.
    assert_review(
        candidate(
            "Жительница Южно-Сахалинска лишилась денег при попытке купить щенка в интернете",
            "Полиция расследует дистанционное мошенничество.",
            url="https://sakhalinmedia.ru/news/2607890/",
        ),
        approved=True,
        category="sakh_chp",
    )

    # 7. Fatal road accident on Iturup is a local emergency.
    assert_review(
        candidate(
            "Водитель Урала погиб при опрокидывании грузовика на Итурупе",
            "Грузовой автомобиль сошел с проезжей части и опрокинулся в кювет.",
            url="https://sakhalinmedia.ru/news/2607800/",
        ),
        approved=True,
        category="sakh_chp",
    )

    # 8. A current Russia-Japan policy statement is legitimate geopolitics.
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

    # 9. Clicky routine traffic enforcement cannot fill the feed as serious news.
    traffic = assert_review(
        candidate(
            "Трое пьяных, шесть без прав: на Сахалине поймали почти 100 нарушителей ГАИ",
            "Инспекторы провели профилактический рейд и пресекли нарушения ПДД.",
            url="https://sakhalinmedia.ru/news/2607802/",
        ),
        approved=False,
    )
    assert traffic.get("subtype") == "traffic_enforcement", traffic

    # 10. Federal gasification is Russia/economy, not local Sakhalin content.
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

    # Exact historical bug: NATO must not be found inside 'санаторий'.
    assert "foreign" not in gate.infer_topics(
        "Не санаторий и не дача — пенсионеры нашли место у моря"
    )
    assert "foreign" in gate.infer_topics(
        "НАТО усиливает военное присутствие в Европе"
    )


def proportion_and_order_regressions():
    assert sum(director.TARGET_COUNTS.values()) == director.ROLLING_WINDOW == 12
    assert director.TARGET_COUNTS["local"] == 6
    assert set(director.SECOND_SLOT_BY_HOUR.values()) == {
        "world_ru", "ru_safety", "ru_pol", "ru_eco", "geo", "it"
    }

    items = [
        candidate(
            "РусГидро открыло центр обслуживания в Поронайске Сахалинской области",
            "Центр рассчитан на 20 тысяч жителей района.",
            url="https://sakhalinmedia.ru/news/local-order/",
        ),
        candidate(
            "Правительство России утвердило новую программу развития регионов",
            "Решение принято правительством Российской Федерации.",
            source="TASS",
            url="https://tass.ru/politika/order/",
            category="ru_pol",
        ),
        candidate(
            "Россия и Япония обсудили состояние двусторонних отношений",
            "Москва и Токио провели переговоры.",
            source="Interfax",
            url="https://www.interfax.ru/world/order/",
            category="geo",
        ),
        candidate(
            "OpenAI представила новую модель искусственного интеллекта",
            "Компания объявила о выпуске новой модели для разработчиков.",
            source="BBC Technology",
            url="https://www.bbc.com/news/technology-order/",
            category="it",
        ),
    ]

    ordered, report = director.direct_candidates(
        {"last_posts": []},
        items,
        category_map=publisher.core.b.CAT,
        now=datetime(2026, 9, 3, 13, 0, tzinfo=timezone(timedelta(hours=11))),
        ai_reviewer=None,
    )
    assert len(ordered) >= 2, report
    assert ordered[0]["category_key"] in {"sakh", "sakh_chp", "sakh_quake"}, report
    assert ordered[1]["category_key"] == "ru_pol", report
    assert report["scheduled_second_group"] == "ru_pol", report


def repetitive_subtype_regression():
    prior = []
    for index in range(2):
        prior.append({
            "title": f"Сахалинец перевел мошенникам {index + 1} миллион рублей",
            "source_text_excerpt": "Полиция расследует дистанционное мошенничество.",
            "source": "SakhalinMedia.ru",
            "url": f"https://sakhalinmedia.ru/news/old-fraud-{index}/",
            "category_key": "sakh_chp",
        })

    new_fraud = candidate(
        "Житель Южно-Сахалинска перевел мошенникам 3 миллиона рублей",
        "Полиция расследует дистанционное мошенничество.",
        url="https://sakhalinmedia.ru/news/new-fraud/",
        category="sakh_chp",
    )
    strong_local = candidate(
        "После аварии в Южно-Сахалинске восстановили теплоснабжение 30 домов",
        "Коммунальные службы устранили повреждение сети, затронувшее жителей города.",
        url="https://sakhalinmedia.ru/news/heating/",
        category="sakh_chp",
    )

    ordered, report = director.direct_candidates(
        {"last_posts": prior},
        [new_fraud, strong_local],
        category_map=publisher.core.b.CAT,
        now=datetime(2026, 9, 3, 7, 0, tzinfo=timezone(timedelta(hours=11))),
        ai_reviewer=None,
    )
    assert all(item["url"] != new_fraud["url"] for item in ordered), report
    review = report["by_url"][new_fraud["url"]]
    assert review["reason"] == "subtype_quota_exhausted", review




def openrouter_resilience_regression():
    class FakeResponse:
        def __init__(self, payload, status_code=200, text=""):
            self._payload = payload
            self.status_code = status_code
            self.text = text
            self.headers = {}

        def json(self):
            return self._payload

    responses = [
        FakeResponse({
            "model": "free/empty",
            "choices": [{"message": {"content": ""}}],
        }),
        FakeResponse({
            "model": "free/invalid",
            "choices": [{"message": {"content": "not-json"}}],
        }),
        FakeResponse({
            "model": "free/valid",
            "choices": [{"message": {"content": '{"ok": true}'}}],
        }),
    ]
    calls = []

    def fake_post(url, **kwargs):
        assert url == editorial.core.b.OPENROUTER_URL
        calls.append(kwargs)
        return responses.pop(0)

    env_names = (
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
        "OPENROUTER_FALLBACK_MODELS",
        "OPENROUTER_MAX_ATTEMPTS",
        "OPENROUTER_RETRY_BASE_SECONDS",
    )
    saved_env = {name: os.environ.get(name) for name in env_names}
    saved_post = editorial.core.b.requests.post
    saved_circuit = editorial._OPENROUTER_CIRCUIT_OPEN
    saved_reason = editorial._OPENROUTER_CIRCUIT_REASON
    stat_names = (
        "openrouter_empty_content",
        "openrouter_model_fallback",
        "openrouter_attempts",
        "openrouter_retries",
        "openrouter_invalid_json",
        "openrouter_success",
        "openrouter_circuit_open",
    )
    saved_stats = {
        name: editorial.core.b.STATS.get(name)
        for name in stat_names
    }

    try:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        os.environ["OPENROUTER_MODEL"] = ""
        os.environ["OPENROUTER_FALLBACK_MODELS"] = ""
        os.environ["OPENROUTER_MAX_ATTEMPTS"] = "3"
        os.environ["OPENROUTER_RETRY_BASE_SECONDS"] = "0"
        editorial._OPENROUTER_CIRCUIT_OPEN = False
        editorial._OPENROUTER_CIRCUIT_REASON = ""
        editorial.core.b.requests.post = fake_post
        for name in stat_names:
            editorial.core.b.STATS[name] = 0

        assert publisher.core.b.openrouter is editorial.resilient_openrouter
        raw = publisher.core.b.openrouter(
            [{"role": "user", "content": "Верни JSON"}],
            max_tokens=128,
        )
        assert publisher.core.b.parse_obj(raw) == {"ok": True}
        assert len(calls) == 3
        for call in calls:
            body = call["json"]
            assert body["model"] == "openrouter/free"
            assert body["response_format"] == {"type": "json_object"}
            assert body["provider"]["require_parameters"] is True
            assert body["provider"]["allow_fallbacks"] is True
            assert "temperature" not in body
        assert editorial.core.b.STATS["openrouter_empty_content"] == 1
        assert editorial.core.b.STATS["openrouter_invalid_json"] == 1
        assert editorial.core.b.STATS["openrouter_attempts"] == 3
        assert editorial.core.b.STATS["openrouter_retries"] == 2
        assert editorial.core.b.STATS["openrouter_success"] == 1
        assert editorial.core.b.STATS["openrouter_model_fallback"] == 1
        assert editorial._OPENROUTER_CIRCUIT_OPEN is False
    finally:
        editorial.core.b.requests.post = saved_post
        editorial._OPENROUTER_CIRCUIT_OPEN = saved_circuit
        editorial._OPENROUTER_CIRCUIT_REASON = saved_reason
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        for name, value in saved_stats.items():
            if value is None:
                editorial.core.b.STATS.pop(name, None)
            else:
                editorial.core.b.STATS[name] = value


def extractive_first_regression():
    item = candidate(
        "В Южно-Сахалинске временно изменили схему движения автобусов",
        (
            "Администрация Южно-Сахалинска сообщила, что с понедельника движение "
            "автобусов по улице Ленина будет организовано по временной схеме. "
            "Изменение связано с ремонтом дорожного покрытия и будет действовать "
            "до завершения работ на указанном участке."
        ),
        url="https://sakhalinmedia.ru/news/extractive-first/",
    )

    called = {"value": False}
    original_generate = publisher.prod.core.generate_grounded
    original_extract_count = publisher.core.b.STATS.get("extractive_fallback")
    original_first_count = publisher.core.b.STATS.get("extractive_first")

    def unexpected_generate(*args, **kwargs):
        called["value"] = True
        raise AssertionError("Russian extractive post must not call OpenRouter")

    try:
        publisher.prod.core.generate_grounded = unexpected_generate
        publisher.core.b.STATS["extractive_fallback"] = 0
        publisher.core.b.STATS["extractive_first"] = 0
        row = publisher.prod.valid_post_v99(item)
        assert row is not None
        assert row.get("editorial_mode") == "extractive_fallback"
        assert called["value"] is False
        assert publisher.core.b.STATS["extractive_first"] == 1
    finally:
        publisher.prod.core.generate_grounded = original_generate
        if original_extract_count is None:
            publisher.core.b.STATS.pop("extractive_fallback", None)
        else:
            publisher.core.b.STATS["extractive_fallback"] = original_extract_count
        if original_first_count is None:
            publisher.core.b.STATS.pop("extractive_first", None)
        else:
            publisher.core.b.STATS["extractive_first"] = original_first_count


def director_ai_outage_regression():
    borderline = candidate(
        "На Сахалине изменили график работы областной библиотеки",
        "Новый график действует для посетителей учреждения до конца месяца.",
        url="https://sakhalinmedia.ru/news/director-ai-outage/",
        category="sakh",
        score=100,
    )
    initial = director.review_candidate(borderline)
    assert initial["approved"] is True, initial
    assert initial["needs_ai_review"] is True, initial
    assert initial["seriousness"] < initial["threshold"] + 4, initial

    ordered, report = director.direct_candidates(
        {"last_posts": []},
        [borderline],
        category_map=publisher.core.b.CAT,
        now=datetime(2026, 9, 4, 7, 0, tzinfo=timezone(timedelta(hours=11))),
        ai_reviewer=lambda _: {},
    )
    assert [item["url"] for item in ordered] == [borderline["url"]], report
    final = report["by_url"][borderline["url"]]
    assert final["approved"] is True, final
    assert final["reason"] == "approved", final


def media_and_version_regressions():
    assert publisher.VERSION == "stable-v11.0"
    assert publisher.media.VERSION == "stable-v11.0"
    assert publisher.core.VERSION == "stable-v11.0"
    assert publisher.core.b.IMAGE_REQUIRED is True

    good_media = {
        "image": b"x" * 12000,
        "image_url": "https://sakhalinmedia.ru/f/big/news-photo.jpg",
        "image_hash": "f" * 40,
    }
    assert media._is_source_media(good_media)[0] is True
    assert media._is_source_media({})[0] is False


def main():
    screenshot_regressions()
    proportion_and_order_regressions()
    repetitive_subtype_regression()
    openrouter_resilience_regression()
    extractive_first_regression()
    director_ai_outage_regression()
    media_and_version_regressions()
    print("stable-v11.0 production self-test: ALL PASS")


if __name__ == "__main__":
    main()
