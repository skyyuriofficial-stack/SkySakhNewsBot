# Shared robust text builder for SkySakhNews editorial pipeline.
# Goal: produce short factual Russian Telegram text from noisy source snippets without AI/API.
# It removes Interfax/RSS boilerplate, duplicate fragments, broken tails and near-duplicate paragraphs.

import html
import re
import difflib
from typing import Dict, List, Tuple

BOILERPLATE_MARKERS = [
    "читать далее", "continue reading", "sign in", "support us", "под катом", "подробнее",
    "реклама", "на правах рекламы", "подписывайтесь", "комментировать", "text settings",
    "sections forum", "subscribe search", "prefer the guardian",
]

PROPAGANDA_PHRASES = [
    "беззащитным детям", "каратели", "нацисты", "террористический режим", "прицельно ударили по спящим",
]

FOOTERS = {
    "🌍 Мир о России": "МИР О РОССИИ",
    "🇷🇺 РФ / война и безопасность": "РФ | ВОЙНА И БЕЗОПАСНОСТЬ",
    "🇷🇺 РФ / происшествия": "РФ | ПРОИСШЕСТВИЯ",
    "🇷🇺 РФ / экономика": "РФ | ЭКОНОМИКА",
    "🇷🇺 РФ / законы и политика": "РФ | ЗАКОНЫ И ПОЛИТИКА",
    "🧭 Геополитика": "ГЕОПОЛИТИКА",
    "🌐 Мировые IT": "МИРОВЫЕ IT",
    "💻 IT / технологии": "IT / ТЕХНОЛОГИИ",
    "🎮 Игры / индустрия": "ИГРОВАЯ ИНДУСТРИЯ",
    "📍 Сахалин": "САХАЛИН",
}


def esc(value) -> str:
    return html.escape(str(value or ""), quote=False)


def attr(value) -> str:
    return html.escape(str(value or ""), quote=True)


def clean_html(value) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\u00a0", " ")
    text = text.replace("“", "\"").replace("”", "\"").replace("«", "\"").replace("»", "\"")
    return re.sub(r"\s+", " ", text).strip(" -—")


def norm(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def cyrillic_ratio(text: str) -> float:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text or "")
    if not letters:
        return 0.0
    cyr = re.findall(r"[А-Яа-яЁё]", text or "")
    return len(cyr) / max(1, len(letters))


def remove_interfax_prefix(text: str) -> str:
    # Prefer the clean article part after INTERFAX.RU marker when present.
    parts = re.split(r"INTERFAX\.RU\s*-\s*", text, flags=re.I)
    if len(parts) > 1 and len(parts[-1].strip()) > 80:
        text = parts[-1]
    text = re.sub(r"\bМосква\.\s*\d{1,2}\s+[А-Яа-я]+\.\s*", "", text)
    text = re.sub(r"\bINTERFAX\.RU\s*-\s*", "", text, flags=re.I)
    return text


def remove_consecutive_word_repeats(text: str) -> str:
    words = text.split()
    changed = True
    # Remove exact consecutive duplicate blocks: A B C A B C -> A B C.
    while changed and len(words) > 10:
        changed = False
        max_n = min(90, len(words) // 2)
        for n in range(max_n, 4, -1):
            i = 0
            out = []
            local_changed = False
            while i < len(words):
                if i + 2 * n <= len(words) and [w.lower().strip('.,;:!?"') for w in words[i:i+n]] == [w.lower().strip('.,;:!?"') for w in words[i+n:i+2*n]]:
                    out.extend(words[i:i+n])
                    i += 2 * n
                    local_changed = True
                else:
                    out.append(words[i])
                    i += 1
            if local_changed:
                words = out
                changed = True
                break
    return " ".join(words)


def strip_broken_tail(sentence: str) -> str:
    s = clean_html(sentence)
    s = re.sub(r"\"[А-Яа-яA-Za-z0-9\s,;:—-]{0,35}$", "", s).strip()
    s = re.sub(r"[А-Яа-яA-Za-z]+-[А-Яа-яA-Za-z]{0,3}$", "", s).strip()
    return s.strip(" -—,;:")


def sim_norm(text: str) -> str:
    text = norm(text)
    text = re.sub(r"\"[^\"\n]{0,260}\"", " ", text)
    text = re.sub(r"\b(сообщил[аи]?|заявил[аи]?|написал[аи]?|уточнил[аи]?|добавил[аи]?|по данным|по словам|в оперштабе|в региональном оперштабе|пресс-служб[а-я]*|губернатор[^.]{0,80})\b", " ", text)
    text = re.sub(r"[^a-zа-я0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def too_similar(a: str, b: str) -> bool:
    aa, bb = sim_norm(a), sim_norm(b)
    if not aa or not bb:
        return False
    ratio = difflib.SequenceMatcher(None, aa, bb).ratio()
    wa, wb = set(aa.split()), set(bb.split())
    jaccard = len(wa & wb) / max(1, len(wa | wb))
    return ratio >= 0.72 or jaccard >= 0.58


def valid_sentence(s: str) -> bool:
    low = norm(s)
    if len(s) < 38:
        return False
    if any(x in low for x in BOILERPLATE_MARKERS):
        return False
    if any(x in low for x in PROPAGANDA_PHRASES):
        return False
    if cyrillic_ratio(s) < 0.55:
        return False
    # Drop broken long fragments without sentence ending.
    if len(s) > 150 and not re.search(r"[.!?…]$", s):
        return False
    return True


def split_sentences(text: str) -> List[str]:
    text = clean_source_text(text)
    raw = re.split(r"(?<=[.!?…])\s+", text)
    out = []
    for part in raw:
        s = strip_broken_tail(part)
        if not s:
            continue
        if not re.search(r"[.!?…]$", s) and len(s) < 150:
            s += "."
        if valid_sentence(s):
            out.append(s[:420])
    return out


def clean_source_text(text: str) -> str:
    text = clean_html(text)
    text = remove_interfax_prefix(text)
    text = re.sub(r"\b[A-ZА-ЯЁ][a-zа-яё]+\.\s*\d{1,2}\s+[а-яё]+\.\s*", "", text)
    text = remove_consecutive_word_repeats(text)
    # Remove exact duplicate sentences while preserving order.
    parts = re.split(r"(?<=[.!?…])\s+", text)
    cleaned = []
    for p in parts:
        p = strip_broken_tail(p)
        if not p:
            continue
        if any(too_similar(p, old) for old in cleaned):
            continue
        cleaned.append(p)
    return " ".join(cleaned).strip()


def body_from_item(item: Dict, max_paragraphs: int = 2) -> List[str]:
    candidates: List[str] = []
    source_text = item.get("source_text") or item.get("summary") or ""
    candidates.extend(split_sentences(source_text))
    for raw in item.get("body") or []:
        candidates.extend(split_sentences(raw))
    out: List[str] = []
    title = clean_title(item)
    for s in candidates:
        if too_similar(s, title):
            continue
        if any(too_similar(s, old) for old in out):
            continue
        out.append(s)
        if len(out) >= max_paragraphs:
            break
    return out


def clean_title(item: Dict) -> str:
    title = clean_html(item.get("title_ru") or item.get("title_original") or item.get("title") or "")
    title = remove_consecutive_word_repeats(title)
    title = re.sub(r"\s+", " ", title).strip(" -—.:;")
    if len(title) > 115:
        title = title[:112].rstrip(" ,;:-—") + "…"
    return title


def make_post(category: str, title: str, body: List[str], url: str, source: str) -> str:
    footer = FOOTERS.get(category, category.upper())
    paragraphs = "\n\n".join(esc(x) for x in body if x)
    if paragraphs:
        return f"{esc(category)}\n\n<b>{esc(title)}</b>\n\n{paragraphs}\n\n{esc(footer)} · <a href=\"{attr(url)}\">{esc(source or 'Источник')}</a>"
    return f"{esc(category)}\n\n<b>{esc(title)}</b>\n\n{esc(footer)} · <a href=\"{attr(url)}\">{esc(source or 'Источник')}</a>"


def build_post_parts(item: Dict, category: str) -> Tuple[str, List[str]]:
    return clean_title(item), body_from_item(item, max_paragraphs=2)


def build_post_text(item: Dict, category: str) -> Tuple[str, List[str], str]:
    title, body = build_post_parts(item, category)
    post = make_post(category, title, body, item.get("url") or "", item.get("source") or "Источник")
    return title, body, post


def is_post_usable(title: str, body: List[str]) -> bool:
    if not title or cyrillic_ratio(title + " " + " ".join(body)) < 0.55:
        return False
    # One paragraph is acceptable for short factual wires; do not force duplicates.
    return len(body) >= 1
