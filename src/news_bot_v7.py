import os
from io import BytesIO

# v7: автономный режим.
# Бот не ждёт пользователя: если источник не дал рабочую картинку,
# сам делает новостную обложку и публикует через sendPhoto.
os.environ["IMAGE_REQUIRED"] = "0"

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

import news_bot_v6 as base

base.IMAGE_REQUIRED = False

EXTRA_BAD = [
    "мошен