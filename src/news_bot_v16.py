# v16: final source-stream guard over v15.
# Prevents source/category mismatch before publication.

import re
import urllib.parse
import news_bot_v15 as v15

b = v15.b

HABR_BLOCK = ["магнит", "кассет", "kenwood", "tdk", "lufs", "true peak", "клиппинг", "аудио", "магнитофон"]
HARD_IT = ["openai", "chatgpt", "gpt", "nvidia", "google", "microsoft", "apple", "android", "ios", "linux", "windows", "python", "github", "сервер", "код", "софт", "прилож", "программ", "разработ", "чип", "процессор", "ии", "нейросет"]
LOCAL_HOSTS = ("astv.ru", "sakhalinmedia.ru", "sakh.online", "skr.su", "sakh.com")
IT_CATS = ("🌐 Мировые IT", "💻 IT / технологии")
LOCAL_CATS = ("📍 Сахалин",)


def host(url):
    try:
        return urllib.parse.urlparse(url or "").netloc.lower().replace("www.", "")
    except Exception:
        return ""


def text_of(item):
    return f"{item.get('title','')} {item.get('summary','')} {item.get('source_text','')} {item.get('category_hint','')} {item.get('source','')} {item.get('url','')}".lower()


def contains(text, markers):
    raw = " " + (text or "").lower() + " "
    for marker in markers:
        m = marker.lower().strip()
        if not m:
            continue
        if re.fullmatch(r"[a-z0-9]+", m):
            if re.search(rf"(?<![a-z0-9]){re.escape(m)}(?![a-z0-9])", raw):
                return True
        elif m in raw:
            return True
    return False


def is_habr(item):
    return "habr" in (item.get("source") or "").lower() or "habr.com" in host(item.get("url"))


def is_local(item):
    t = text_of(item)
    h = host(item.get("url"))
    return any(x in h for x in LOCAL_HOSTS) or bool(b.terms(t, b.LOCAL))


old_collect = b.collect


def collect(state):
    out = []
    for item in old_collect(state):
        cat = item.get("category_hint") or item.get("category") or ""
        text = text_of(item)
        if is_habr(item):
            if cat not in IT_CATS:
                b.STATS["category_skip"] = b.STATS.get("category_skip", 0) + 1
                b.log("skip habr_wrong_stream: " + item.get("title", "")[:90])
                continue
            if contains(text, HABR_BLOCK) and not contains(text, HARD_IT):
                b.STATS["category_skip"] = b.STATS.get("category_skip", 0) + 1
                b.log("skip habr_offtopic: " + item.get("title", "")[:90])
                continue
        if cat in LOCAL_CATS and not is_local(item):
            b.STATS["category_skip"] = b.STATS.get("category_skip", 0) + 1
            b.log("skip local_wrong_source: " + item.get("title", "")[:90])
            continue
        out.append(item)
    return out


b.collect = collect

if __name__ == "__main__":
    b.main()
