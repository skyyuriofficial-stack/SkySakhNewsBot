import os, re, json, html, time, hashlib, urllib.parse
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests
import feedparser

STATE = "state.json"
SAKH_TZ = timezone(timedelta(hours=11))
MAX_AGE_HOURS = int(os.getenv("MAX_AGE_HOURS", "36"))
POSTS_PER_RUN = int(os.getenv("POSTS_PER_RUN", "2"))
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.getenv("OPENROUTER_MODEL") or "openrouter/free"

FOOTER = {
    "sakh": ("📍 Сахалин", "ЧП | САХАЛИН"),
    "russia": ("🇷🇺 Россия", "РОССИЯ"),
    "world_ru": ("🌍 Мир о России", "МИР О РОССИИ"),
    "geo": ("🧭 Геополитика", "МИР | Г