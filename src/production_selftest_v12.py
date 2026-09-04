"""Regression tests for the strict stable-v12.0 editorial system."""

from __future__ import annotations

from datetime import datetime, timezone

import post_publish_audit_v12 as post_audit
import publisher_v12 as publisher
import quality_v12 as quality


def candidate(title, text, *, source="SakhalinMedia.ru", url="https://example.test/news/1", category="sakh"):
    return {
        "title": title, "source_text": text, "source": source, "url": url,
        "category_key": category, "category": category, "footer": category,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "title_hash": url[-8:], "topic_cluster": category + ":" + url[-6:],
        "image": b"x" * 12000,
        "image_url": "https://example.test/image/" + url[-4:] + ".jpg",
        "image_hash": (url[-1:] or "a") * 40,
    }


def expect(item, approved, category=None, reason=None, subtype=None):
    result = quality.review(item)
    assert result["approved"] is approved, (item["title"], result)
    if category is not None:
        assert result.get("corrected_category") == category, (item["title"], result)
    if reason is not None:
        assert result.get("reason") == reason, (item["title"], result)
    if subtype is not None:
        assert result.get("subtype") == subtype, (item["title"], result)
    return result


def exact_feed_failures():
    expect(candidate(
        "Полиция на Сахалине ищет Александра Ледяева, чтобы вернуть ему вещи и документы",
        "Если вы знаете, где находится мужчина, просьба сообщить информацию по телефону.",
        source="ASTV", category="sakh_chp", url="https://astv.ru/news/return-documents",
    ), False, reason="service_notice_not_release_news")

    violent = candidate(
        "Предъявили обвинение: сахалинца, который ранил и удерживал в сожительницу, взяли под стражу",
        "Мужчина нанес женщине пять ножевых ранений. Пострадавшая скончалась в больнице.",
        source="ASTV", category="sakh", url="https://astv.ru/news/violent-crime",
    )
    result = expect(violent, True, category="sakh_chp", subtype="violent_crime")
    assert result["score"] >= 90, result
    assert "удерживал в сожительницу" not in quality.sanitize_title(violent["title"])
    assert "удерживал сожительницу" in quality.sanitize_title(violent["title"])

    expect(candidate(
        "Пять пьяных, 16 без прав: какие правила нарушили водители Сахалина за сутки",
        "Инспекторы ГАИ провели профилактические мероприятия. ДТП с пострадавшими не было.",
        category="sakh", url="https://sakhalinmedia.ru/news/routine-traffic",
    ), False, reason="routine_traffic_statistics")


def earlier_screenshot_failures():
    expect(candidate(
        "В Южно-Сахалинске наградили волонтёров Победы знаком Доброволец Сахалинской области",
        "Состоялась торжественная церемония награждения.",
        url="https://sakhalinmedia.ru/news/ceremony",
    ), False, reason="ceremony_or_congratulation")
    expect(candidate(
        "В этот день, 3 сентября, в 1945 году Советская армия одержала победу над Японией",
        "Исторический календарный материал.", category="geo",
        url="https://sakhalinmedia.ru/news/history",
    ), False, reason="history_calendar_not_current_news")
    expect(candidate(
        "Ветерана Вячеслава Гаврилова поздравили с Днем Победы над милитаристской Японией",
        "Глава города выразил благодарность ветерану.", source="Sakh.online",
        category="geo", url="https://sakh.online/news/veteran",
    ), False, reason="ceremony_or_congratulation")
    expect(candidate(
        "Не санаторий и не дача — пенсионеры нашли райское место у моря себе по карману",
        "Недорогой отдых в Анапе и Ейске от 1000 рублей.", category="geo",
        url="https://sakhalinmedia.ru/news/lifestyle",
    ), False, reason="lifestyle_or_seo")

    expect(candidate(
        "РусГидро открыло расчётно-информационный центр в Поронайске Сахалинской области",
        "Центр обслужит более 20 тысяч жителей муниципального района.",
        url="https://sakhalinmedia.ru/news/rushydro",
    ), True, category="sakh", subtype="infrastructure")
    expect(candidate(
        "Прогноз ВТБ: рынок сбережений в России в 2026 году вырастет на 8%",
        "Объем средств в российских банках достигнет 71 трлн рублей.", category="sakh",
        url="https://sakhalinmedia.ru/news/vtb",
    ), True, category="ru_eco", subtype="economy")
    expect(candidate(
        "Жительница Южно-Сахалинска лишилась 650 тысяч рублей при попытке купить щенка",
        "Полиция расследует дистанционное мошенничество.", category="sakh",
        url="https://sakhalinmedia.ru/news/fraud",
    ), True, category="sakh_chp", subtype="fraud")
    expect(candidate(
        "Водитель грузовика погиб при опрокидывании автомобиля на Итурупе",
        "Машина сошла с проезжей части, водитель погиб.", category="sakh",
        url="https://sakhalinmedia.ru/news/fatal-dtp",
    ), True, category="sakh_chp")
    expect(candidate(
        "Путин заявил об ухудшении российско-японских отношений из-за позиции Токио",
        "Президент России возложил ответственность на японское правительство.",
        category="geo", url="https://sakhalinmedia.ru/news/japan",
    ), True, category="geo")


def proportions_and_selection():
    assert quality.ROLLING_WINDOW == 20
    assert quality.TARGET_COUNTS == {
        "local": 6, "ru_pol": 4, "ru_eco": 4,
        "ru_safety": 3, "world": 2, "it": 1,
    }
    assert sum(quality.TARGET_COUNTS.values()) == 20

    items = [
        candidate(
            "В Южно-Сахалинске после аварии восстановили тепло в 30 домах",
            "Коммунальная авария затронула жителей Южно-Сахалинска.",
            category="sakh", url="https://example.test/local",
        ),
        candidate(
            "Правительство России утвердило закон о новом порядке контроля",
            "Решение принято правительством и направлено в Госдуму.",
            source="TASS", category="ru_pol", url="https://example.test/politics",
        ),
        candidate(
            "Центробанк России сохранил ключевую ставку",
            "Решение влияет на кредиты, сбережения и инфляцию.",
            source="Interfax", category="ru_eco", url="https://example.test/economy",
        ),
        candidate(
            "В результате атаки БПЛА в российском регионе пострадали два человека",
            "Минобороны и власти региона сообщили об атаке.",
            source="Interfax", category="ru_security", url="https://example.test/security",
        ),
        candidate(
            "США и Россия провели переговоры по вопросам безопасности",
            "Делегации обсудили международную повестку.",
            source="Reuters", category="world_ru", url="https://example.test/world",
        ),
        candidate(
            "OpenAI представила новую модель искусственного интеллекта",
            "Компания выпустила новую модель для разработчиков.",
            source="BBC Technology", category="it", url="https://example.test/it",
        ),
    ]
    ordered, report = quality.select({"last_posts": []}, items, publisher.core.b.CAT, limit=2)
    assert len(ordered) >= 2, report
    assert ordered[0]["_quality_v12"]["group"] != ordered[1]["_quality_v12"]["group"], report
    assert all(item["_quality_v12"]["approved"] for item in ordered), report


def post_publish_guard_test():
    item = candidate(
        "В Южно-Сахалинске после аварии восстановили тепло в 30 домах",
        "Коммунальная авария затронула жителей Южно-Сахалинска.",
        category="sakh_chp", url="https://example.test/audited",
    )
    review = quality.review(item)
    post = {
        "title": review["title"], "source_title": item["title"],
        "source_text_excerpt": item["source_text"], "source": item["source"],
        "url": item["url"], "category_key": review["corrected_category"],
        "quality_v12": {**quality.compact(review), "approved": True, "prepublication_checked": True},
        "with_image": True, "image_url": item["image_url"], "image_hash": item["image_hash"],
        "publish_method": "sendPhoto/upload_original_html", "final_body": [item["source_text"]],
    }
    result = post_audit.audit_post(post)
    assert result["ok"] is True, result
    post["category_key"] = "sakh"
    result = post_audit.audit_post(post)
    assert result["ok"] is False, result
    assert any("category_mismatch" in x for x in result["failures"]), result


def version_and_chain():
    assert publisher.VERSION == "stable-v12.0"
    assert publisher.core.VERSION == "stable-v12.0"
    assert publisher.core.b.IMAGE_REQUIRED is True


def main():
    exact_feed_failures()
    earlier_screenshot_failures()
    proportions_and_selection()
    post_publish_guard_test()
    version_and_chain()
    print("stable-v12.0 strict editorial self-test: ALL PASS")


if __name__ == "__main__":
    main()
