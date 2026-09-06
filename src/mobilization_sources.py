from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Tuple

import feedparser
import requests

UA = {"User-Agent": "Mozilla/5.0 SkySakhNewsBot/1.0 (+https://t.me/SkySakhNews)"}

MOBILIZATION_RE = re.compile(
    r"мобилизац|запасник|резервист|военком|повестк|военн(?:ые|ых) сбор|"
    r"барс\b|категори.{0,20}[«\"']?д[»\"']?|контрактн.{0,30}(набор|служб)|"
    r"комплектован|кадров.{0,20}(дефицит|давлен)|личн.{0,20}состав|"
    r"mobiliz|reservist|reserve call|conscription|manpower|force generation|"
    r"recruit(?:ment|ing)|draft notice",
    re.I,
)
RUSSIA_RE = re.compile(r"росси|russia|russian|кремл|putin|путин|минобор|moscow|москва", re.I)
EXCLUDE_RE = re.compile(
    r"china\s*&\s*taiwan|china and taiwan|тайван|taiwan update|"
    r"2022.*мобилизац|история мобилизац|как было в 2022",
    re.I,
)

DIRECT_FEEDS: List[Tuple[str, str, str, int]] = [
    ("Interfax", "ru_media", "https://www.interfax.ru/rss.asp", 88),
    ("BBC World", "bbc", "https://feeds.bbci.co.uk/news/world/rss.xml", 91),
    ("Guardian World", "ru_media", "https://www.theguardian.com/world/rss", 84),
]

MONTHS = {
    1: "january", 2: "february", 3: "march", 4: "april", 5: "may", 6: "june",
    7: "july", 8: "august", 9: "september", 10: "october", 11: "november", 12: "december",
}


def clean(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_entry_dt(entry: Dict[str, Any]) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw:
            try:
                dt = parsedate_to_datetime(str(raw))
                return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
            except Exception:
                pass
    return None


def excerpt_around(text: str, pattern: re.Pattern[str] = MOBILIZATION_RE, radius: int = 1100) -> str:
    match = pattern.search(text or "")
    if not match:
        return clean(text)[:1800]
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return clean(text[start:end])[:2400]


def is_relevant(row: Dict[str, Any]) -> bool:
    title = clean(row.get("title"))
    summary = clean(row.get("summary"))
    text = f"{title} {summary}"
    group = str(row.get("group") or "")
    if EXCLUDE_RE.search(text):
        return False
    if group == "isw":
        if "russian offensive campaign assessment" not in title.lower():
            return False
        return bool(MOBILIZATION_RE.search(text))
    if group == "law":
        return "1322096-8" in text or "1322096" in text or bool(MOBILIZATION_RE.search(text))
    if group == "official":
        return bool(MOBILIZATION_RE.search(text))
    return bool(RUSSIA_RE.search(text) and MOBILIZATION_RE.search(text))


def filter_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [row for row in rows if isinstance(row, dict) and is_relevant(row)]


def fetch_direct_feeds() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for source, group, url, trust in DIRECT_FEEDS:
        try:
            response = requests.get(url, headers=UA, timeout=20)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except Exception as exc:
            print(f"direct feed error {source}: {exc}", flush=True)
            continue
        for entry in feed.entries[:100]:
            title = clean(entry.get("title"))
            summary = clean(entry.get("summary") or entry.get("description"))
            dt = parse_entry_dt(entry)
            if dt and now - dt > timedelta(days=8):
                continue
            row = {
                "group": group,
                "trust": trust,
                "source": source,
                "title": title,
                "summary": summary[:1400],
                "url": clean(entry.get("link")),
                "published_utc": dt.isoformat() if dt else None,
            }
            if is_relevant(row):
                out.append(row)
    return out


def _isw_url(day) -> str:
    slug = f"russian-offensive-campaign-assessment-{MONTHS[day.month]}-{day.day}-{day.year}"
    return f"https://understandingwar.org/research/russia-ukraine/{slug}/"


def _fetch_isw_day(day) -> Dict[str, Any] | None:
    day_iso = day.isoformat()
    url = _isw_url(day)
    try:
        response = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
        if response.status_code >= 400:
            return None
        page = response.text[:1_500_000]
    except Exception as exc:
        print(f"ISW fetch error {day_iso}: {exc}", flush=True)
        return None
    text = clean(page)
    title_match = re.search(r"<title[^>]*>(.*?)</title>", page, flags=re.I | re.S)
    title = clean(title_match.group(1) if title_match else f"Russian Offensive Campaign Assessment, {day_iso}")
    row = {
        "group": "isw",
        "trust": 96,
        "source": "Institute for the Study of War",
        "title": title,
        "summary": excerpt_around(text),
        "url": response.url or url,
        "published_utc": f"{day_iso}T00:00:00+00:00",
    }
    return row if is_relevant(row) else None


def fetch_isw_daily() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    today = datetime.now(timezone.utc).date()
    for offset in range(0, 9):
        row = _fetch_isw_day(today - timedelta(days=offset))
        if row:
            out.append(row)
    return out


def fetch_kremlin_index() -> List[Dict[str, Any]]:
    url = "https://kremlin.ru/events/president/news/page/1"
    out: List[Dict[str, Any]] = []
    try:
        response = requests.get(url, headers=UA, timeout=20)
        response.raise_for_status()
        page = response.text[:1_500_000]
    except Exception as exc:
        print(f"Kremlin index error: {exc}", flush=True)
        return out

    seen = set()
    for match in re.finditer(r'href=["\'](/events/president/(?:news|transcripts)/\d+)["\']', page, flags=re.I):
        path = match.group(1)
        if path in seen:
            continue
        seen.add(path)
        context = clean(page[max(0, match.start() - 1100): match.end() + 1100])
        row = {
            "group": "official",
            "trust": 100,
            "source": "Президент России / Kremlin.ru",
            "title": context[:320],
            "summary": context[:1800],
            "url": "https://kremlin.ru" + path,
            "published_utc": None,
        }
        if is_relevant(row):
            out.append(row)
        if len(out) >= 8:
            break
    return out


def fetch_bill_pages() -> List[Dict[str, Any]]:
    sources = [
        ("ГАРАНТ — досье законопроекта №1322096-8", "https://base.garant.ru/414784137/", 96),
        ("ГАРАНТ — текст законопроекта №1322096-8", "https://base.garant.ru/411685332/", 96),
        ("ГАРАНТ — пояснительная записка №1322096-8", "https://base.garant.ru/411685333/", 96),
        ("Государственная Дума — законопроект №1322096-8", "https://sozd.duma.gov.ru/bill/1322096-8", 100),
    ]
    out: List[Dict[str, Any]] = []
    for name, url, trust in sources:
        try:
            response = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
            if response.status_code >= 400:
                continue
            page = response.text[:1_200_000]
        except Exception as exc:
            print(f"bill page error {name}: {exc}", flush=True)
            continue
        text = clean(page)
        if "1322096-8" not in text and "1322096" not in text:
            continue
        title_match = re.search(r"<title[^>]*>(.*?)</title>", page, flags=re.I | re.S)
        title = clean(title_match.group(1) if title_match else name)
        marker = text.find("1322096")
        summary = clean(text[max(0, marker - 700): marker + 3200]) if marker >= 0 else text[:2200]
        row = {
            "group": "law",
            "trust": trust,
            "source": name,
            "title": title,
            "summary": summary[:2600],
            "url": response.url or url,
            "published_utc": None,
        }
        if is_relevant(row):
            out.append(row)
    return out


def collect_fallback() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    rows.extend(fetch_isw_daily())
    rows.extend(fetch_kremlin_index())
    rows.extend(fetch_bill_pages())
    rows.extend(fetch_direct_feeds())

    seen = set()
    unique = []
    for row in filter_rows(rows):
        marker = clean(row.get("url")) or re.sub(r"\W+", " ", clean(row.get("title")).lower()).strip()
        if not marker or marker in seen:
            continue
        seen.add(marker)
        unique.append(row)
    unique.sort(key=lambda x: (int(x.get("trust") or 0), str(x.get("published_utc") or "")), reverse=True)
    return unique[:50]
