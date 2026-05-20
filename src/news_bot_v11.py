# v11 compatibility entrypoint.
# Active implementation: v12 plus final classification patch.

import re
import news_bot_v12 as v12

b = v12.b

FOREIGN_MARKERS = [
    "usa", "united states", "сша", "америк", "trump", "трамп", "senate", "сенат",
    "iran", "иран", "israel", "израил", "gaza", "газа", "china", "китай",
    "eu", "евросоюз", "европа", "nato", "нато",
]


def contains_any(text, terms):
    raw = " " + (text or "").lower() + " "
    for term in terms:
        t = term.lower().strip()
        if not t:
            continue
        if re.fullmatch(r"[a-z0-9.]+", t):
            if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", raw):
                return True
        elif t in raw:
            return True
    return False


def classify_entrypoint(source_type, title, rss_text, page_desc, url):
    text = f"{title} {rss_text} {page_desc} {url}".lower()
    explicit_russia = v12.has_explicit_russia(text)

    # Interfax /world/ and other foreign-only Russian-language stories are not RF domestic security.
    if source_type == "ru" and not explicit_russia and ("/world/" in (url or "") or contains_any(text, FOREIGN_MARKERS)):
        return "🧭 Геополитика", 88

    # World source: Russia stream only with explicit Russia markers.
    if source_type == "world" and not explicit_russia:
        if v12.strong_geopolitics_without_russia(text):
            return "🧭 Геополитика", 88
        return None, 0

    return v12.classify_v12(source_type, title, rss_text, page_desc, url)


b.classify = classify_entrypoint

if __name__ == "__main__":
    b.main()
