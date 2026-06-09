import os
import re
from io import BytesIO

# v7: автономный выпуск.
# Даже если источник не отдаёт рабочую картинку, пост публикуется через sendPhoto
# с автоматически сгенерированной новостной обложкой. Пользователь не участвует.
os.environ["IMAGE_REQUIRED"] = "0"

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

import news_bot_v6 as base
