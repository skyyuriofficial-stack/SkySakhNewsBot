# Deterministic thematic image generator for SkySakhNews.
# Last fallback when source/curated/external image is unavailable.
# Generates neutral, non-text editorial illustrations locally with Pillow.

import hashlib
import io
import math
import random
from typing import Dict, Tuple

from PIL import Image, ImageDraw, ImageFilter

W, H = 1200, 675

PALETTES = {
    "🌍 Мир о России": ((20, 38, 66), (96, 24, 36), (226, 226, 216)),
    "🇷🇺 РФ / война и безопасность": ((18, 28, 38), (82, 96, 106), (196, 84, 64)),
    "🇷🇺 РФ / экономика": ((15, 48, 42), (26, 88, 82), (218, 178, 86)),
    "🇷🇺 РФ / законы и политика": ((25, 38, 64), (78, 58, 92), (220, 205, 160)),
    "🧭 Геополитика": ((18, 32, 58), (64, 82, 112), (214, 190, 130)),
    "🌐 Мировые IT": ((12, 30, 48), (18, 82, 112), (90, 200, 220)),
    "💻 IT / технологии": ((12, 30, 48), (18, 82, 112), (90, 200, 220)),
    "🎮 Игры / индустрия": ((22, 20, 46), (90, 48, 120), (120, 210, 190)),
    "📍 Сахалин": ((12, 54, 68), (48, 102, 92), (224, 210, 150)),
}


def _seed(item: Dict) -> int:
    raw = f"{item.get('category') or item.get('category_hint')}|{item.get('title_ru') or item.get('title_original')}|{item.get('url')}"
    return int(hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12], 16)


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
        a = rng.randint(10, 24)
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
    pts = []
    for i in range(9):
        x = 184 + i * 90
        y = base_y - rng.randint(120, 300)
        pts.append((x, y))
    d.line(pts, fill=(*accent, 220), width=6, joint='curve')
    for x, y in pts:
        d.ellipse((x - 10, y - 10, x + 10, y + 10), fill=(*accent, 230))


def _draw_security(d, rng, accent):
    # abstract radar / air-defense / emergency signal, no weapons
    cx, cy = 360, 350
    for r in [90, 155, 220]:
        d.arc((cx - r, cy - r, cx + r, cy + r), 205, 335, fill=(*accent, 120), width=4)
    for a in [-50, -25, 0, 25, 50]:
        rad = math.radians(a)
        d.line((cx, cy, cx + math.cos(rad) * 270, cy + math.sin(rad) * 270), fill=(*accent, 85), width=3)
    d.polygon([(790, 170), (1030, 505), (560, 505)], outline=(*accent, 190), fill=(*accent, 42))
    d.rounded_rectangle((655, 400, 935, 440), radius=16, fill=(*accent, 130))


def _draw_diplomacy(d, rng, accent):
    for i, x in enumerate([250, 430, 610, 790, 970]):
        d.line((x, 170, x, 500), fill=(*accent, 110), width=5)
        d.polygon([(x, 170), (x + 95, 205), (x, 240)], fill=(*accent, 100 + i * 18))
    d.rounded_rectangle((190, 500, 1030, 535), radius=16, fill=(*accent, 120))
    d.ellipse((500, 245, 700, 445), outline=(*accent, 155), width=5)
    d.arc((465, 230, 735, 460), 20, 160, fill=(*accent, 130), width=4)


def _draw_it(d, rng, accent):
    for y in [185, 290, 395]:
        d.rounded_rectangle((230, y, 970, y + 72), radius=18, outline=(*accent, 150), fill=(*accent, 42), width=3)
        for x in range(265, 910, 70):
            d.ellipse((x, y + 26, x + 18, y + 44), fill=(*accent, 150))
    _draw_network(d, rng, accent)


def _draw_games(d, rng, accent):
    d.rounded_rectangle((330, 230, 870, 470), radius=90, fill=(*accent, 65), outline=(*accent, 190), width=5)
    d.ellipse((405, 305, 525, 425), outline=(*accent, 180), width=8)
    d.line((465, 330, 465, 400), fill=(*accent, 180), width=8)
    d.line((430, 365, 500, 365), fill=(*accent, 180), width=8)
    for x, y in [(710, 330), (770, 365), (710, 405), (650, 365)]:
        d.ellipse((x - 18, y - 18, x + 18, y + 18), fill=(*accent, 170))


def _draw_sakhalin(d, rng, accent):
    # abstract island/coastline and city lights
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
    for i in range(11):
        x = rng.randint(-120, W)
        y = rng.randint(-120, H)
        w = rng.randint(100, 330)
        d.rounded_rectangle((x, y, x + w, y + rng.randint(18, 52)), radius=20, fill=(*accent, rng.randint(12, 34)))

    if category == '🇷🇺 РФ / экономика':
        _draw_economy(d, rng, accent)
    elif category == '🇷🇺 РФ / война и безопасность':
        _draw_security(d, rng, accent)
    elif category in ('🌍 Мир о России', '🇷🇺 РФ / законы и политика', '🧭 Геополитика'):
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
