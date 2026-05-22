# Smoke tests for SkySakhNews shared category policy.

from category_policy import resolve_final_category


def check(title: str, summary: str, expected: str) -> None:
    got = resolve_final_category("", title, summary, "Interfax", "https://www.interfax.ru/")
    if got != expected:
        raise AssertionError(f"{title!r}: expected {expected!r}, got {got!r}")
    print(f"ok: {expected} | {title[:80]}")


def main() -> None:
    check(
        "Пашинян заверил, что Армения никогда не будет вовлечена в антироссийскую кампанию",
        "Премьер Армении Никол Пашинян заявил, что Ереван не будет участвовать в антироссийских действиях.",
        "🧭 Геополитика",
    )
    check(
        "Илон Маск проиграл суд OpenAI",
        "Судебное решение по делу OpenAI, Альтмана и Маска касается искусственного интеллекта и Big Tech.",
        "🌐 Мировые IT",
    )
    check(
        "К спин-оффу The Witcher привлекли сценаристку Destiny 2",
        "Игровая индустрия, студии, Steam, Xbox и крупные игровые франшизы.",
        "🎮 Игры / индустрия",
    )
    check(
        "В Брянской области дронами атакована автозаправка, двое мужчин ранены",
        "Атака БПЛА, ПВО, пострадавшие и повреждения объекта.",
        "🇷🇺 РФ / война и безопасность",
    )
    check(
        "Около 90 тыс. человек остались без воды из-за аварии на водопроводе в Хакасии",
        "Авария на водопроводе, коммунальное ЧП, без воды жители пригорода.",
        "🇷🇺 РФ / происшествия",
    )
    check(
        "Россельхозбанк профинансировал зерновую отрасль на 71,3 млрд рублей",
        "Банк, кредит, зерно, сельхоз и финансирование производителей.",
        "🇷🇺 РФ / экономика",
    )
    print("CATEGORY_POLICY_SMOKE_TEST_OK")


if __name__ == "__main__":
    main()
