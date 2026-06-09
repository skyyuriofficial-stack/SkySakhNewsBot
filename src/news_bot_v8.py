import os
from io import BytesIO

os.environ["IMAGE_REQUIRED"] = "0"

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

import news_bot_v6 as b

b.IMAGE_REQUIRED = False
b.POSTS_PER_RUN = int(os.getenv("POSTS_PER_RUN", "2"))

BAD = [
    "подробности уточняются",
    "по мере появления",
    "что известно",
    "суть:",
    "мошенники угрожали задержкой",
    "потеря 13,3 млн рублей",
]
NOISE = "афиша вакансии гороскоп погода реклама конкурс спорт рейтинг матч теннис футбол баскетбол".split()
STRONG_RU