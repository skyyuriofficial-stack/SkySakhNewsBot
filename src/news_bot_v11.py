# v11: priority tweak over v10.
# Puts loud world IT / gaming before Sakhalin in the publication order.

import news_bot_v10 as v10

b = v10.b


def select_order_v11(items):
    # Publication priority for 2 posts per run:
    # 1) Main hard-news block: world about Russia / RF war / economy / hard laws.
    # 2) Loud world IT or gaming.
    # 3) Sakhalin.
    # 4) Remaining candidates by existing score/order.
    main = [x for x in items if x["category_hint"] in (
        "🌍 Мир о России",
        "🇷🇺 РФ / война и безопасность",
        "🇷🇺 РФ / экономика",
        "🇷🇺 РФ / законы и политика",
    )]
    tech_game = [x for x in items if x["category_hint"] in (
        "🌐 Мировые IT",
        "🎮 Игры / индустрия",
    )]
    local = [x for x in items if x["category_hint"] == "📍 Сахалин"]

    ordered = []

    if main:
        ordered.append(main[0])

    # User preference: loud world IT/gaming goes before Sakhalin.
    if tech_game:
        ordered.append(tech_game[0])

    if local:
        ordered.append(local[0])

    for item in main + tech_game + local + items:
        if item not in ordered:
            ordered.append(item)

    return ordered


b.select_order = select_order_v11

if __name__ == "__main__":
    b.main()
