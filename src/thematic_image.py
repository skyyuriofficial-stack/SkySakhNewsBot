# Deterministic semantic image generator for SkySakhNews.
# Last fallback when source/search images are unavailable or rejected.
# Generates neutral editorial illustrations locally with Pillow. No text is drawn on images.

import hashlib
import io
import math
import random
import re
from typing import Dict, Tuple

from PIL import Image, ImageDraw, ImageFilter

W, H = 1200, 675

PALETTES = {
    "🌍 Мир о России": ((20, 38, 66), (96, 24, 36), (226, 226, 216)),
    "🇷🇺 РФ / война и безопасность": ((18, 28, 38), (82, 96, 106), (196, 84, 64)),
    "🇷🇺 РФ / происшествия": ((36, 34, 30), (92, 54, 36), (230, 122, 52)),
    "🇷🇺 РФ / экономика": ((18, 56, 42), (48, 88, 70), (224, 184, 82)),
    "🇷🇺 РФ / законы и политика": ((25, 38, 64), (78, 58, 92), (220, 205, 160)),
    "🧭 Геополитика": ((18, 32, 58), (64, 82, 112), (214, 190, 130)),
    "🌐 Мировые IT": ((12, 30, 48), (18, 82, 112), (90, 200, 220)),
    "💻 IT / технологии": ((12, 30, 48), (18, 82, 112), (90, 200, 220)),
    "🎮 Игры / индустрия": ((22, 20, 46), (90, 48, 120), (120, 210, 190)),
    "📍 Сахалин": ((12, 54, 68), (48, 102, 92), (224, 210, 150)),
}

AGRI_TERMS = ["сельхоз", "сельск", "зерн", "зерно", "пшениц", "аграр", "урож", "посев", "фермер", "россельхозбанк", "агропром"]
BANK_TERMS = ["банк", "кредит", "ставк", "вклад", "ипотек", "финанс", "профинанс", "заем", "заём", "рубл"]
ENERGY_TERMS = ["нефть", "газ", "спг", "уголь", "энергоресурс", "трубопровод", "месторожд", "экспорт"]
INDUSTRY_TERMS = ["завод", "производств", "промышлен", "предприят", "индустр", "металл", "станок"]
FIRE_TERMS = ["пожар", "возгоран", "сгорел", "сгорела", "огонь", "мчс", "пожарн"]
ROAD_TERMS = ["дтп", "авар", "столкнов", "водител", "дорог", "трасс", "микроавтобус", "газель"]
WATER_TERMS = ["водопровод", "водоснаб", "без воды", "труба", "коллектор", "коммуналь", "жкх"]
CRIME_TERMS = ["краж", "мошеннич", "убийств", "напад", "задержан", "полици"]
AVALANCHE_TERMS = ["лавина", "сход лавины", "спасатели", "пропал", "пропали", "горы", "снег", "поисково-спас"]
FLOOD_TERMS = ["наводнение", "паводок", "затоп", "подтоп", "река", "дамба"]
SPACE_TERMS = ["космос", "космич", "тайконавт", "астронавт", "орбит", "шэньчжоу", "тяньгун", "cmsa", "space", "spacecraft", "station", "orbit", "shenzhou", "tiangong"]
MIDDLE_EAST_TERMS = ["трамп", "иран", "тегеран", "сша", "вашингтон", "израил", "саудов", "оаэ", "катар", "бахрейн", "авраам", "iran", "trump", "tehran", "abraham", "israel", "middle east"]


def _seed(item: Dict) -> int:
    raw = f"{item.get('category') or item.get('category_hint')}|{item.get('title_ru') or item.get('title_original')}|{item.get('url')}"
    return int(hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12], 16)


def _text(item: Dict) -> str:
    raw = " ".join(str(item.get(k) or "") for k in ("category", "category_hint", "title_ru", "title_original", "source_text", "post_text", "edited_post_text", "url"))
    return re.sub(r"\s+", " ", raw.lower().replace("ё", "е")).strip()


def _has(text: str, terms) -> bool:
    return any(term in text for term in terms)


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _gradient(bg1: Tuple[int, int, int], bg2: Tuple[int, int, int]) -> Image.Image:
    img = Image.new('RGB', (W, H), bg1)
    pix = img.load()
    for y in range(H):
        t = y / max(1, H - 1)
        for x in range(W):
            radial = ((x - W * 0.72) ** 2 + (y - H * 0.28) ** 2) ** 0.5 / W
            k = min(1.0, max(0.0, t * 0.72 + radial * 0.34))
            pix[x, y] = tuple(_lerp(bg1[i], bg2[i], k) for i in range(3))
    return img


def _noise_overlay(img: Image.Image, rng: random.Random) -> None:
    layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(900):
        x = rng.randint(0, W)
        y = rng.randint(0, H)
        a = rng.randint(8, 20)
        d.point((x, y), fill=(255, 255, 255, a))
    img.alpha_composite(layer)


def _draw_network(d: ImageDraw.ImageDraw, rng: random.Random, color):
    pts = [(rng.randint(120, W - 120), rng.randint(90, H - 90)) for _ in range(26)]
    for i, p in enumerate(pts):
        for q in pts[i + 1:i + 4]:
            if rng.random() < 0.48:
                d.line([p, q], fill=(*color, rng.randint(55, 105)), width=rng.randint(1, 2))
    for x, y in pts:
        r = rng.randint(4, 9)
        d.ellipse((x - r, y - r, x + r, y + r), outline=(*color, 160), width=2)


def _draw_economy(d, rng, accent):
    base_y = 520
    for i in range(9):
        x = 160 + i * 90
        h = rng.randint(70, 240)
        d.rounded_rectangle((x, base_y - h, x + 48, base_y), radius=8, fill=(*accent, 95), outline=(*accent, 150), width=2)
    pts = [(184 + i * 90, base_y - rng.randint(120, 300)) for i in range(9)]
    d.line(pts, fill=(*accent, 220), width=6, joint='curve')
    for x, y in pts:
        d.ellipse((x - 10, y - 10, x + 10, y + 10), fill=(*accent, 230))


def _draw_agriculture(d, rng, accent):
    d.rectangle((0, 0, W, 300), fill=(170, 205, 215, 80))
    d.rectangle((0, 300, W, H), fill=(164, 126, 54, 150))
    vanishing = (W // 2, 305)
    for x in range(-200, W + 220, 95):
        d.line((vanishing[0], vanishing[1], x, H), fill=(*accent, 90), width=3)
    for y in range(340, H, 48):
        d.arc((-120, y - 90, W + 120, y + 90), 0, 180, fill=(*accent, 60), width=2)
    for i in range(16):
        x = 110 + i * 62 + rng.randint(-10, 10)
        y0 = 470 + rng.randint(-20, 30)
        y1 = 255 + rng.randint(-20, 25)
        d.line((x, y0, x + rng.randint(-18, 18), y1), fill=(236, 205, 118, 210), width=4)
        head_x = x + rng.randint(-18, 18)
        for j in range(7):
            yy = y1 + j * 15
            d.ellipse((head_x - 16, yy - 5, head_x + 2, yy + 8), fill=(238, 196, 88, 210))
            d.ellipse((head_x - 2, yy - 5, head_x + 16, yy + 8), fill=(238, 196, 88, 210))
    d.rounded_rectangle((735, 160, 1030, 350), radius=26, fill=(245, 242, 220, 210), outline=(*accent, 210), width=5)


def _draw_bank_credit(d, rng, accent):
    d.rounded_rectangle((210, 170, 990, 500), radius=32, fill=(242, 238, 220, 48), outline=(*accent, 180), width=5)
    for x in [300, 450, 600, 750, 900]:
        d.rounded_rectangle((x - 34, 270, x + 34, 470), radius=12, fill=(*accent, 90), outline=(*accent, 175), width=3)
    d.polygon([(235, 235), (600, 120), (965, 235)], fill=(*accent, 110), outline=(*accent, 190))
    d.rounded_rectangle((260, 485, 940, 525), radius=18, fill=(*accent, 150))


def _draw_energy(d, rng, accent):
    d.rectangle((0, 430, W, H), fill=(20, 45, 52, 130))
    for x in [260, 520, 780, 960]:
        d.line((x, 430, x + rng.randint(-40, 40), 180), fill=(*accent, 130), width=8)
        d.line((x - 80, 430, x + 80, 430), fill=(*accent, 110), width=8)
        d.rectangle((x - 45, 230, x + 45, 285), outline=(*accent, 155), width=5)
    d.line((120, 520, 1080, 520), fill=(*accent, 170), width=10)
    for x in range(150, 1050, 120):
        d.ellipse((x - 12, 508, x + 12, 532), fill=(*accent, 210))


def _draw_industry(d, rng, accent):
    d.rectangle((0, 430, W, H), fill=(38, 48, 50, 130))
    for x in [160, 310, 480, 680, 860]:
        h = rng.randint(120, 260)
        d.rectangle((x, 430 - h, x + 110, 430), fill=(*accent, 68), outline=(*accent, 145), width=3)
        d.rectangle((x + 70, 430 - h - 80, x + 95, 430 - h), fill=(*accent, 95))
    d.line((120, 460, 1080, 460), fill=(*accent, 160), width=6)


def _draw_security(d, rng, accent):
    cx, cy = 360, 350
    for r in [90, 155, 220]:
        d.arc((cx - r, cy - r, cx + r, cy + r), 205, 335, fill=(*accent, 120), width=4)
    for a in [-50, -25, 0, 25, 50]:
        rad = math.radians(a)
        d.line((cx, cy, cx + math.cos(rad) * 270, cy + math.sin(rad) * 270), fill=(*accent, 85), width=3)
    d.polygon([(790, 170), (1030, 505), (560, 505)], outline=(*accent, 190), fill=(*accent, 42))


def _draw_incident(d, rng, accent, text):
    if _has(text, AVALANCHE_TERMS):
        d.rectangle((0, 0, W, H), fill=(32, 46, 58, 110))
        d.polygon([(0, 560), (255, 220), (455, 560)], fill=(218, 228, 232, 210), outline=(*accent, 95))
        d.polygon([(320, 560), (630, 130), (980, 560)], fill=(235, 242, 245, 220), outline=(*accent, 105))
        d.polygon([(760, 560), (1020, 260), (1220, 560)], fill=(210, 225, 232, 200), outline=(*accent, 95))
        for _ in range(70):
            x, y = rng.randint(80, 1120), rng.randint(170, 580)
            d.ellipse((x, y, x + 5, y + 5), fill=(255, 255, 255, rng.randint(90, 170)))
        d.rounded_rectangle((210, 470, 990, 505), radius=16, fill=(*accent, 140))
        for x in [300, 450, 620, 780, 930]:
            d.line((x, 505, x + rng.randint(-35, 35), 560), fill=(*accent, 115), width=5)
    elif _has(text, WATER_TERMS):
        d.rectangle((0, 400, W, H), fill=(18, 70, 88, 150))
        for y in [280, 360, 445]:
            d.rounded_rectangle((160, y, 1040, y + 46), radius=23, fill=(*accent, 105), outline=(*accent, 170), width=4)
        for x in [300, 520, 740, 960]:
            d.ellipse((x - 42, 315, x + 42, 399), outline=(170, 220, 230, 160), width=8)
        for _ in range(28):
            x = rng.randint(190, 1010)
            y = rng.randint(455, 620)
            d.arc((x, y, x + 70, y + 30), 0, 180, fill=(180, 230, 240, 110), width=3)
    elif _has(text, FIRE_TERMS):
        d.rectangle((0, 410, W, H), fill=(38, 32, 28, 155))
        for i, x in enumerate([210, 360, 510, 700, 870]):
            h = rng.randint(120, 260)
            d.polygon([(x, 440), (x + 45, 440 - h), (x + 95, 440)], fill=(240, 104 + i * 7, 42, 140))
            d.polygon([(x + 25, 440), (x + 55, 440 - h + 35), (x + 85, 440)], fill=(250, 185, 72, 120))
        d.rounded_rectangle((210, 310, 990, 370), radius=20, fill=(*accent, 130))
    elif _has(text, ROAD_TERMS):
        d.polygon([(0, H), (470, 210), (730, 210), (W, H)], fill=(60, 65, 68, 135))
        d.line((595, 220, 560, H), fill=(*accent, 180), width=6)
        d.line((650, 220, 700, H), fill=(*accent, 180), width=6)
        d.rounded_rectangle((430, 375, 770, 445), radius=24, fill=(*accent, 120), outline=(*accent, 190), width=4)
        for x in [480, 700]:
            d.ellipse((x, 430, x + 58, 488), fill=(20, 24, 26, 200), outline=(*accent, 160), width=4)
    elif _has(text, CRIME_TERMS):
        d.rounded_rectangle((270, 145, 930, 510), radius=42, fill=(22, 32, 44, 105), outline=(*accent, 170), width=5)
        for y in [230, 305, 380]:
            d.line((350, y, 850, y), fill=(*accent, 145), width=6)
            d.ellipse((310, y - 16, 342, y + 16), fill=(*accent, 165))
    else:
        d.rounded_rectangle((240, 170, 960, 500), radius=36, fill=(*accent, 58), outline=(*accent, 160), width=5)
        d.polygon([(600, 235), (720, 455), (480, 455)], fill=(*accent, 140))


def _draw_diplomacy(d, rng, accent):
    for i, x in enumerate([250, 430, 610, 790, 970]):
        d.line((x, 170, x, 500), fill=(*accent, 110), width=5)
        d.polygon([(x, 170), (x + 95, 205), (x, 240)], fill=(*accent, 100 + i * 18))
    d.rounded_rectangle((190, 500, 1030, 535), radius=16, fill=(*accent, 120))
    d.ellipse((500, 245, 700, 445), outline=(*accent, 155), width=5)
    d.arc((465, 230, 735, 460), 20, 160, fill=(*accent, 130), width=4)


def _draw_middle_east_diplomacy(d, rng, accent):
    d.rounded_rectangle((210, 210, 990, 505), radius=36, fill=(235, 220, 190, 38), outline=(*accent, 155), width=5)
    # Two negotiation blocks across a table, deliberately symbolic, no text/flags.
    d.rounded_rectangle((305, 305, 505, 430), radius=24, fill=(*accent, 90), outline=(*accent, 165), width=4)
    d.rounded_rectangle((695, 305, 895, 430), radius=24, fill=(*accent, 80), outline=(*accent, 165), width=4)
    d.rounded_rectangle((450, 450, 750, 485), radius=18, fill=(*accent, 135))
    for x in [370, 430, 760, 830]:
        d.ellipse((x - 28, 250, x + 28, 306), fill=(*accent, 130), outline=(*accent, 190), width=3)
    d.arc((385, 120, 815, 540), 210, 330, fill=(*accent, 110), width=5)
    d.arc((320, 155, 880, 580), 200, 340, fill=(*accent, 60), width=3)


def _draw_it(d, rng, accent):
    for y in [185, 290, 395]:
        d.rounded_rectangle((230, y, 970, y + 72), radius=18, outline=(*accent, 150), fill=(*accent, 42), width=3)
        for x in range(265, 910, 70):
            d.ellipse((x, y + 26, x + 18, y + 44), fill=(*accent, 150))
    _draw_network(d, rng, accent)


def _draw_space(d, rng, accent):
    d.rectangle((0, 0, W, H), fill=(4, 15, 34, 180))
    for _ in range(120):
        x, y = rng.randint(20, W - 20), rng.randint(20, H - 20)
        a = rng.randint(90, 220)
        d.ellipse((x, y, x + 2, y + 2), fill=(230, 240, 255, a))
    # planet limb
    d.ellipse((-260, 430, 1460, 1240), outline=(90, 180, 210, 130), width=16)
    d.arc((-220, 455, 1420, 1215), 190, 350, fill=(70, 150, 190, 95), width=10)
    # orbital station / spacecraft silhouette
    cx, cy = 610, 310
    d.rounded_rectangle((cx - 90, cy - 28, cx + 90, cy + 28), radius=14, fill=(*accent, 150), outline=(210, 235, 240, 140), width=3)
    d.rectangle((cx - 205, cy - 16, cx - 95, cy + 16), fill=(*accent, 100), outline=(210, 235, 240, 100))
    d.rectangle((cx + 95, cy - 16, cx + 205, cy + 16), fill=(*accent, 100), outline=(210, 235, 240, 100))
    d.line((cx, cy - 85, cx, cy + 85), fill=(210, 235, 240, 120), width=5)
    d.ellipse((cx - 24, cy - 24, cx + 24, cy + 24), fill=(220, 245, 255, 120))
    d.arc((cx - 260, cy - 150, cx + 260, cy + 150), 195, 345, fill=(*accent, 100), width=4)


def _draw_games(d, rng, accent):
    d.rounded_rectangle((330, 230, 870, 470), radius=90, fill=(*accent, 65), outline=(*accent, 190), width=5)
    d.ellipse((405, 305, 525, 425), outline=(*accent, 180), width=8)
    d.line((465, 330, 465, 400), fill=(*accent, 180), width=8)
    d.line((430, 365, 500, 365), fill=(*accent, 180), width=8)
    for x, y in [(710, 330), (770, 365), (710, 405), (650, 365)]:
        d.ellipse((x - 18, y - 18, x + 18, y + 18), fill=(*accent, 170))


def _draw_sakhalin(d, rng, accent):
    pts = [(500, 95), (560, 150), (535, 235), (610, 315), (575, 430), (650, 560), (565, 610), (485, 500), (430, 410), (460, 300), (420, 200)]
    d.line(pts, fill=(*accent, 190), width=12, joint='curve')
    d.line([(80, 535), (1120, 535)], fill=(*accent, 80), width=3)
    for _ in range(70):
        x = rng.randint(130, 1070)
        y = rng.randint(470, 610)
        d.rectangle((x, y, x + rng.randint(4, 10), y + rng.randint(4, 10)), fill=(*accent, rng.randint(90, 180)))


def generate_thematic_image(item: Dict) -> Tuple[bytes, str, str]:
    category = item.get('category') or item.get('category_hint') or '🧭 Геополитика'
    bg1, bg2, accent = PALETTES.get(category, PALETTES['🧭 Геополитика'])
    rng = random.Random(_seed(item))
    text = _text(item)

    base = _gradient(bg1, bg2).convert('RGBA')
    glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for _ in range(9):
        x = rng.randint(50, W - 50)
        y = rng.randint(30, H - 30)
        r = rng.randint(90, 260)
        gd.ellipse((x - r, y - r, x + r, y + r), fill=(*accent, rng.randint(14, 35)))
    glow = glow.filter(ImageFilter.GaussianBlur(45))
    base.alpha_composite(glow)

    d = ImageDraw.Draw(base)
    for _ in range(7):
        x = rng.randint(-120, W)
        y = rng.randint(-120, H)
        w = rng.randint(100, 330)
        d.rounded_rectangle((x, y, x + w, y + rng.randint(18, 52)), radius=20, fill=(*accent, rng.randint(8, 24)))

    if _has(text, SPACE_TERMS):
        _draw_space(d, rng, accent)
    elif category == '🇷🇺 РФ / экономика':
        if _has(text, AGRI_TERMS):
            _draw_agriculture(d, rng, accent)
        elif _has(text, ENERGY_TERMS):
            _draw_energy(d, rng, accent)
        elif _has(text, BANK_TERMS):
            _draw_bank_credit(d, rng, accent)
        elif _has(text, INDUSTRY_TERMS):
            _draw_industry(d, rng, accent)
        else:
            _draw_economy(d, rng, accent)
    elif category == '🇷🇺 РФ / происшествия':
        _draw_incident(d, rng, accent, text)
    elif category == '🇷🇺 РФ / война и безопасность':
        _draw_security(d, rng, accent)
    elif category in ('🌍 Мир о России', '🇷🇺 РФ / законы и политика', '🧭 Геополитика'):
        if _has(text, MIDDLE_EAST_TERMS):
            _draw_middle_east_diplomacy(d, rng, accent)
        else:
            _draw_diplomacy(d, rng, accent)
    elif category in ('🌐 Мировые IT', '💻 IT / технологии'):
        _draw_it(d, rng, accent)
    elif category == '🎮 Игры / индустрия':
        _draw_games(d, rng, accent)
    elif category == '📍 Сахалин':
        _draw_sakhalin(d, rng, accent)
    else:
        _draw_network(d, rng, accent)

    _noise_overlay(base, rng)
    base = base.convert('RGB')
    out = io.BytesIO()
    base.save(out, format='JPEG', quality=92, optimize=True)
    return out.getvalue(), 'image/jpeg', 'thematic.jpg'
