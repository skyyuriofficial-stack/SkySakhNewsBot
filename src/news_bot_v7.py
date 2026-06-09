import os
from io import BytesIO

# v7: полностью автономный выпуск.
# Если источник не отдаёт рабочую картинку, бот сам делает новостную обложку
# и всё равно публикует через sendPhoto, без участия пользователя.
os.environ["IMAGE_REQUIRED"] = "0"

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

import news_bot_v6 as base

base.IMAGE_REQUIRED = False

EXTRA_BAD_PHRASES = [
    "мошенники угрожали задержкой",
    "потеря 13,3 млн рублей",
    "подробности уточняются",
    "по мере появления",
    "что известно",
    "суть:",
]

LOCAL_NOISE = "афиша вакансии гороскоп погода реклама конкурс спорт рейтинг".split()
GLOBAL_NO