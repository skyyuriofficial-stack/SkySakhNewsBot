# Smoke tests for story-level image relevance policy.
# These tests validate metadata-based guards without network calls.

from image_pipeline import ImageCandidate, topic_key, relevance_score


def article(category, title, source_text=""):
    return {
        "category": category,
        "title_ru": title,
        "title_original": title,
        "source_text": source_text,
        "body": [],
        "url": "https://example.com/news",
        "source": "test",
    }


def candidate(url="https://commons.wikimedia.org/test.jpg", query="", reason=""):
    return ImageCandidate(
        url=url,
        source="external_search",
        filename=url.rsplit("/", 1)[-1],
        query_used=query,
        reason=reason,
        data=b"test",
    )


def expect_topic(item, expected):
    got = topic_key(item)
    if got != expected:
        raise AssertionError(f"topic expected={expected!r}, got={got!r}, title={item.get('title_ru')!r}")
    print(f"ok topic: {expected} | {item.get('title_ru')[:80]}")


def expect_bad(item, cand, token_hint):
    score, reason, hits, bad_hits, entity_hits = relevance_score(item, cand)
    if not bad_hits:
        raise AssertionError(f"expected bad hit {token_hint!r}; score={score}; reason={reason}; hits={hits}; entity_hits={entity_hits}")
    print(f"ok reject metadata: bad_hits={bad_hits[:4]} | {item.get('title_ru')[:70]}")


def expect_entity_required(item, cand):
    score, reason, hits, bad_hits, entity_hits = relevance_score(item, cand)
    if entity_hits:
        raise AssertionError(f"expected no entity hits, got={entity_hits}; reason={reason}")
    print(f"ok entity required blocks generic image: topic={topic_key(item)} | {item.get('title_ru')[:70]}")


def expect_positive(item, cand):
    score, reason, hits, bad_hits, entity_hits = relevance_score(item, cand)
    if bad_hits or not hits:
        raise AssertionError(f"expected positive match; score={score}; reason={reason}; hits={hits}; bad={bad_hits}; entities={entity_hits}")
    print(f"ok positive image match: topic={topic_key(item)} | hits={hits[:4]}")


def main():
    middle_east = article(
        "🧭 Геополитика",
        "Трамп сообщил, что США и Иран близки к соглашению",
        "США, Иран, Тегеран, соглашение, переговоры, Ближний Восток, Трамп.",
    )
    expect_topic(middle_east, "diplomacy_middle_east")
    expect_bad(
        middle_east,
        candidate(query="diplomacy summit flags", reason="Uzbekistan postage stamp commemorative postal issue"),
        "stamp",
    )
    expect_entity_required(
        middle_east,
        candidate(query="international diplomacy meeting", reason="government leaders summit flags IRENA Ukraine Armenia"),
    )
    expect_positive(
        middle_east,
        candidate(query="Trump Iran diplomacy talks agreement", reason="Trump Iran United States Tehran diplomacy talks agreement Middle East"),
    )

    space = article(
        "🌐 Мировые IT",
        "Китайский корабль Шэньчжоу-23 пристыковался к станции Тяньгун",
        "Тайконавты, космический корабль, орбитальная станция, CMSA.",
    )
    expect_topic(space, "space")
    expect_bad(space, candidate(query="spacecraft docking orbital station", reason="Uzbekistan postage stamp souvenir sheet"), "stamp")
    expect_positive(space, candidate(query="Shenzhou Tiangong space station", reason="Shenzhou Tiangong spacecraft orbital space station taikonaut"))

    avalanche = article(
        "🇷🇺 РФ / происшествия",
        "Спасатели нашли двух человек после схода лавины в Чечне",
        "Лавина, горы, снег, поисково-спасательные работы.",
    )
    expect_topic(avalanche, "incident_avalanche")
    expect_bad(avalanche, candidate(query="computer chip technology", reason="semiconductor processor circuit chip"), "chip")
    expect_positive(avalanche, candidate(query="avalanche mountain rescue snow", reason="avalanche mountain snow rescue emergency"))

    water = article(
        "🇷🇺 РФ / происшествия",
        "Жители остались без воды после аварии на водопроводе",
        "Коммунальная авария, водопровод, ремонт трубы.",
    )
    expect_topic(water, "incident_water")
    expect_bad(water, candidate(query="road accident emergency response", reason="road car vehicle traffic accident"), "road")
    expect_positive(water, candidate(query="water pipe repair utility workers", reason="water pipeline repair municipal utility workers"))

    print("IMAGE_PIPELINE_SMOKE_TEST_OK")


if __name__ == "__main__":
    main()
