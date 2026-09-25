from __future__ import annotations

import editorial_hardening

editorial_hardening.install()

import runtime_source_hardening

runtime_source_hardening.install()

import editorial_policy as policy


def main() -> int:
    repeated_lead = (
        "Восстановление кровли пострадавшего от пожара дома в Южно-Сахалинске начнётся уже 12 сентября."
    )
    dirty = {
        "title": "Восстановление кровли дома в Южно-Сахалинске начнётся 12 сентября",
        "source_text": (
            repeated_lead + " " + repeated_lead + " "
            "Подрядчик должен сначала обследовать несущие конструкции и определить объём восстановительных работ."
        ),
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
    assert "source_text_sanitized" in editorial_hardening.source_quality_warnings(dirty)
    repaired_dirty = editorial_hardening.repair_row(dirty, dirty_row)
    assert not editorial_hardening.content_quality_issues(dirty, repaired_dirty), repaired_dirty
    assert len(repaired_dirty.get("body") or []) >= 2, repaired_dirty

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
    repaired_identity = editorial_hardening.repair_row(identity, identity_row)
    assert repaired_identity["title_ru"].startswith("Пешехода "), repaired_identity
    assert not editorial_hardening.content_quality_issues(identity, repaired_identity), repaired_identity

    malformed = {
        "title": "Авария в Ногликах",
        "source_text": "Авария произошла в Ногликах. По предварительным данным, пострадал человек.",
        "category_key": "sakh_chp",
    }
    malformed_row = {
        "title_ru": malformed["title"],
        "body": [
            "Авария произошла в Ногликах По предварительным данным, пострадал человек.",
            "Обстоятельства происшествия устанавливаются.",
        ],
    }
    assert "body_missing_sentence_boundary" in editorial_hardening.content_quality_issues(malformed, malformed_row)
    repaired_malformed = editorial_hardening.repair_row(malformed, malformed_row)
    assert "Ногликах. По предварительным" in repaired_malformed["body"][0], repaired_malformed

    malformed_astv = {
        "title": "Столкнулся с Suzuki и скрылся: в Южно-Сахалинске ищут свидетелей аварии на улице Вокзальной",
        "source_text": (
            "ДТП случилось днем 13 сентября в районе дома № 50 "
            "Госавтоинспекция Южно-Сахалинска ищет аварии, которая произошла "
            "в областном центре 13 сентября в 13:40. "
            "В тот день у дома №50 на улице Вокзальной автомобиль столкнулся с Suzuki Solio и скрылся."
        ),
        "category_key": "sakh_chp",
    }
    malformed_astv_row = {
        "title_ru": malformed_astv["title"],
        "body": [
            "ДТП случилось днем 13 сентября в районе дома № 50 Госавтоинспекция Южно-Сахалинска ищет аварии, которая произошла в областном центре 13 сентября в 13:40.",
            "В тот день у дома №50 на улице Вокзальной автомобиль столкнулся с Suzuki Solio и скрылся.",
        ],
    }
    malformed_astv_issues = editorial_hardening.content_quality_issues(malformed_astv, malformed_astv_row)
    assert "body_malformed_source_phrase" in malformed_astv_issues, malformed_astv_issues

    magadan = {
        "title": "В Магадане молодой человек осуждён за мошенничество на 34 млн рублей",
        "source_text": (
            "Магаданский городской суд приговорил 22-летнего мужчину к 5 годам лишения свободы. "
            "Суд приговорил 22-летнего участника организованной группы к 5 годам колонии "
            "Преступление было совершено организованной группой: летом 2025 года они убедили "
            "жительницу Магадана продать акции и передать деньги. "
            "Подпишись на самые важные новости Сахалинской области в MAX!"
        ),
        "category_key": "ru_incident",
    }
    magadan_row = {
        "title_ru": magadan["title"],
        "body": [
            "Магаданский городской суд приговорил 22-летнего мужчину к 5 годам лишения свободы.",
            "Суд приговорил 22-летнего участника организованной группы к 5 годам колонии Преступление было совершено организованной группой: летом 2025 года они убедили жительницу Магадана продать акции и передать деньги.",
        ],
    }
    assert "body_missing_sentence_boundary" in editorial_hardening.content_quality_issues(magadan, magadan_row)
    repaired_magadan = editorial_hardening.repair_row(magadan, magadan_row)
    assert "колонии. Преступление" in repaired_magadan["body"][1], repaired_magadan
    assert "Подпишись" not in editorial_hardening.dedupe_source_text(magadan["source_text"])
    assert not editorial_hardening.content_quality_issues(magadan, repaired_magadan), repaired_magadan

    corporate_loans = {
        "title": "4,8 трлн рублей реструктуризаций: объём проблемных кредитов бизнеса вырос на 60%",
        "source_text": (
            "Объём рискованных реструктуризаций кредитов бизнеса на конец июня 2026 года достиг 4,8 трлн рублей против 3 трлн годом ранее. "
            "Такие данные содержатся в отчёте ЦБ Речь идёт о ссудах, которые банки переоформляют на более мягких условиях, "
            "если у заёмщика уже возникли проблемы с выплатами или есть риск появления просрочки."
        ),
        "category_key": "ru_eco",
    }
    corporate_loans_row = {
        "title_ru": corporate_loans["title"],
        "body": [
            "Объём рискованных реструктуризаций кредитов бизнеса на конец июня 2026 года достиг 4,8 трлн рублей против 3 трлн годом ранее.",
            "Такие данные содержатся в отчёте ЦБ Речь идёт о ссудах, которые банки переоформляют на более мягких условиях, если у заёмщика уже возникли проблемы с выплатами или есть риск появления просрочки.",
        ],
    }
    assert "body_missing_sentence_boundary" in editorial_hardening.content_quality_issues(corporate_loans, corporate_loans_row)
    repaired_corporate_loans = editorial_hardening.repair_row(corporate_loans, corporate_loans_row)
    assert "отчёте ЦБ. Речь идёт" in repaired_corporate_loans["body"][1], repaired_corporate_loans
    assert not editorial_hardening.content_quality_issues(corporate_loans, repaired_corporate_loans), repaired_corporate_loans

    eclipse = {
        "title": "Неизвестный столкнулся с Mitsubishi Eclipse Cross и скрылся с места ДТП в Южно-Сахалинске",
        "source_text": (
            "ГАИ ищет очевидцев Госавтоинспекция Южно-Сахалинска ищет очевидцев аварии, которая произошла "
            "в областном центре 4 сентября в 06:36. В то утро неизвестный водитель на неустановленной машине "
            "у дома №34 на улице А. Буюклы столкнулся с припаркованным автомобилем Mitsubishi Eclipse Cross и скрылся. "
            "Если вы были очевидцем этого ДТП, откликнитесь: 789-844."
        ),
        "category_key": "sakh_chp",
    }
    eclipse_row = {
        "title_ru": eclipse["title"],
        "body": [
            "ГАИ ищет очевидцев Госавтоинспекция Южно-Сахалинска ищет очевидцев аварии, которая произошла в областном центре 4 сентября в 06:36.",
            "В то утро неизвестный водитель на неустановленной машине у дома №34 на улице А.",
        ],
    }
    eclipse_issues = editorial_hardening.content_quality_issues(eclipse, eclipse_row)
    assert "body_contains_source_heading_prefix" in eclipse_issues, eclipse_issues
    repaired_eclipse = editorial_hardening.repair_row(eclipse, eclipse_row)
    assert repaired_eclipse["body"][0].startswith("Госавтоинспекция Южно-Сахалинска"), repaired_eclipse
    assert "А. Буюклы столкнулся" in repaired_eclipse["body"][1], repaired_eclipse
    assert repaired_eclipse["body"][1].endswith("и скрылся."), repaired_eclipse
    assert not editorial_hardening.content_quality_issues(eclipse, repaired_eclipse), repaired_eclipse

    horizon = {
        "title": "Аномальный поворот: на въезде у \"Горизонта\" опять ДТП - в пострадавшей машине дети",
        "source_text": (
            "Грузовичок остался без заднего моста. В Южно-Сахалинске 18 сентября произошла очередная авария "
            "на повороте к ЖК \"Горизонт\". Не разъехались легковушка и грузовичок. По словам очевидцев, "
            "в пострадавшем от удара Toyota Raum вместе со взрослыми были трое детей разных возрастов. "
            "\" А грузовичок почти доехал до бывшего поста ГАИ. У него нет заднего моста\", - рассказал информатор. "
            "Горожане уже называют этот поворот аномальным - аварии здесь происходят довольно часто."
        ),
        "category_key": "sakh_chp",
    }
    horizon_row = {
        "title_ru": horizon["title"],
        "body": [
            "В Южно-Сахалинске 18 сентября произошла очередная авария на повороте к ЖК \"Горизонт\".",
            "По словам очевидцев, в пострадавшем от удара Toyota Raum вместе со взрослыми были трое детей разных возрастов. \" А грузовичок почти доехал до бывшего поста ГАИ.",
        ],
    }
    horizon_issues = editorial_hardening.content_quality_issues(horizon, horizon_row)
    assert "body_truncated_inside_quote" in horizon_issues, horizon_issues
    repaired_horizon = editorial_hardening.repair_row(horizon, horizon_row)
    assert repaired_horizon["body"][1].count('"') % 2 == 0, repaired_horizon
    assert "У него нет заднего моста\", - рассказал информатор." in repaired_horizon["body"][1], repaired_horizon
    assert not editorial_hardening.content_quality_issues(horizon, repaired_horizon), repaired_horizon

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

    fire_a = {
        "title": "Прокуратура проверит причины пожара в доме на Тихоокеанской в Южно-Сахалинске",
        "source_text": "Прокуратура организовала проверку после пожара в многоквартирном доме на улице Тихоокеанской.",
        "category_key": "sakh_chp",
    }
    fire_b = {
        "title": "Прокуратура начала проверку после пожара в доме на улице Тихоокеанской в Южно-Сахалинске",
        "source_text": "После пожара в многоквартирном доме на Тихоокеанской прокуратура начала проверку причин происшествия.",
        "category_key": "sakh_chp",
    }
    assert editorial_hardening.duplicate_event(fire_a, fire_b), (fire_a, fire_b)

    tym_fire_a = {
        "title": "Пожарные нашли тело женщины при тушении квартиры в Тымовском районе",
        "source_text": (
            "Трагедия произошла 17 сентября в селе Красная Тымь. Огнеборцы обнаружили тело "
            "42-летней женщины во время тушения пожара в квартире дома на улице Юбилейной. "
            "Следователи не нашли признаков насильственной смерти и назначили судебно-медицинскую экспертизу."
        ),
        "category_key": "sakh_chp",
    }
    tym_fire_b = {
        "title": "Следователи выяснят причины гибели женщины при пожаре в селе Тымовского района",
        "source_text": (
            "17 сентября в квартире дома по улице Юбилейной обнаружили тело 42-летней местной жительницы. "
            "Признаков насильственной смерти не выявлено. Для установления причины гибели назначили экспертизу."
        ),
        "category_key": "sakh_chp",
    }
    assert editorial_hardening.duplicate_event(tym_fire_a, tym_fire_b), (tym_fire_a, tym_fire_b)

    different_fire = {
        "title": "Следователи проверят гибель женщины при пожаре в Тымовском районе",
        "source_text": (
            "В другом населенном пункте при пожаре в доме на улице Центральной погибла 61-летняя женщина."
        ),
        "category_key": "sakh_chp",
    }
    assert not editorial_hardening.duplicate_event(tym_fire_a, different_fire), (tym_fire_a, different_fire)

    malformed_source = (
        "Следователи не обнаружили признаков насильственной смерти Огнеборцы обнаружили тело "
        "42-летней женщины во время тушения пожара."
    )
    assert "смерти. Огнеборцы" in editorial_hardening.dedupe_source_text(malformed_source)

    print("hardening selftest: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
