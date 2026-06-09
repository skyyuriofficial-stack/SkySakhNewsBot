import os
from io import BytesIO

# v7: автономная публикация без белых карточек.
# Если источник не отдал картинку, бот сам генерирует новостную обложку и всё равно публикует через sendPhoto.
os.environ["IMAGE_REQUIRED"] = "0"

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

import news_bot_v6 as base

base.IMAGE_REQUIRED = False

EXTRA_BAD = [
    "мошенники угрожали задержкой",
    "потеря 13,3 млн рублей",
    "подробности уточняются",
    "по мере появления",
    "что известно",
    "суть:",
]


def load_font(size, bold=False):
    names = ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"] if bold else ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def wrap_text(draw, text, font, max_width):
    words = base.clean(text).split()
    lines, current = [], ""
    for word in words:
        probe = (current + " " + word).strip()
        width = draw.textbbox((0, 0), probe, font=font)[2]
        if width <= max_width:
            current = probe
        else:
            if current:
                lines