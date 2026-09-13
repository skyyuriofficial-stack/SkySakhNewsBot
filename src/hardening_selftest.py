from __future__ import annotations

from datetime import datetime

import editorial_hardening

editorial_hardening.install()

import editorial_policy as policy


def main() -> int:
    dirty = {
        "title": "Восстановление кровли дома в Южно-Сахалинске начнётся 12 сентября",
        "source_text": "Восстановление кровли начнётся 12 сентября. Восстановление кровли начнётся 12 сентября.",
        "category_key": "sakh_chp",
    }
    dirty_row = {
        "title_ru": dirty["title"],
        "body": [
            "Работы по восстановлению кровли начнутся 12 сентября.",
            "Ни одна часть содержания сайта ASTV.RU не может быть воспроизведена без письменного разрешения.",
        ],
    }
    issues = editorial_hardening.content_quality_issues(dirty, dirty_row)
    assert "body_contains_publisher_boilerplate" in issues, issues
    assert "source_lead_duplicated" in issues, issues

    identity = {
        "title": "Сахалинца госпитализировали после ДТП с пьяным водителем",
        "source_text": "Пешеход пострадал в ДТП. Его личность в настоящее время не установлена.",
        "category_key": "sakh_chp",
    }
    identity_row = {
        "title_ru": identity["title"],
        "body": [
            "Пешеход пострадал после наезда автомобиля.",
            "Его доставили в медицинское учреждение.",
        ],
    }
    assert "unsupported_sakhalin_resident_identity" in editorial_hardening.content_quality_issues(identity, identity_row)

    sinegorsk = policy.classify({
        "title": "Синегорск остался без света после аварии на линии",
        "source_text": "Энергетики устраняют последствия аварии в Синегорске.",
        "source": "Sakh.online",
        "url": "https://sakh.online/news/example",
        "category_key": "ru_incident",
    })
    assert sinegorsk.group == "local", sinegorsk.to_dict()
    assert sinegorsk.category_key in {"sakh", "sakh_chp"}, sinegorsk.to_dict()

    nepal = policy.classify({
        "title": "Наводнение в Непале: спасены тысячи человек",
        "source_text": "Наводнение произошло в Непале и затронуло районы у границы с Китаем.",
        "source": "TASS",
        "url": "https://tass.ru/mezhdunarodnaya-panorama/example",
        "category_key": "ru_incident",
    })
    assert nepal.category_key != "ru_incident", nepal.to_dict()
    assert nepal.group in {"world", None}, nepal.to_dict()

    print("hardening selftest: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
