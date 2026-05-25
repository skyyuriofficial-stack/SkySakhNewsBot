import re
import time
from datetime import datetime

import editorial_queue as q
from image_pipeline import (
    ImageDecision,
    candidate_to_file,
    decision_to_dict,
    remember_image_in_state,
    resolve_article_image,
    bytes_fingerprint,
    external_thematic_search,
    generated_candidate,
)


def log(message: str) -> None:
    try:
        q.b.log(message)
    except Exception:
        print(message)


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def has_any(text: str, terms) -> bool:
    text = norm(text)
    return any(norm(t) in text for t in terms)


def article_for_image(draft: dict) -> dict:
    item = q.item_for_publish(draft, image_file=None)
    item.update({
        "category": draft.get("category") or draft.get("category_hint"),
        "category_hint": draft.get("category") or draft.get("category_hint"),
        "title_ru": draft.get("title_ru") or draft.get("title_original"),
        "title_original": draft.get("title_original") or draft.get("title_ru"),
        "body": draft.get("body") or [],
        "source_text": draft.get("source_text") or "",
        "post_text": draft.get("post_text") or "",
        "edited_post_text": draft.get("edited_post_text") or "",
        "image_url": draft.get("image_url"),
        "image_mode": draft.get("image_mode"),
        "source": draft.get("source") or item.get("source"),
        "url": draft.get("url") or item.get("url"),
    })
    return item


def candidate_words(candidate) -> str:
    return norm(" ".join([
        str(getattr(candidate, "url", "") or ""),
        str(getattr(candidate, "filename", "") or ""),
        str(getattr(candidate, "query_used", "") or ""),
        str(getattr(candidate, "reason", "") or ""),
        str(getattr(candidate, "image_kind", "") or ""),
    ]))


def article_words(article: dict) -> str:
    return norm(" ".join([
        str(article.get("category") or ""),
        str(article.get("category_hint") or ""),
        str(article.get("title_ru") or ""),
        str(article.get("title_original") or ""),
        str(article.get("source_text") or ""),
        " ".join(str(x) for x in (article.get("body") or [])),
        str(article.get("post_text") or ""),
        str(article.get("edited_post_text") or ""),
    ]))


def is_forbidden_source_text_card(article: dict, candidate) -> bool:
    if not candidate or candidate.source != "source":
        return False
    haystack = " ".join([
        str(article.get("source") or ""),
        str(article.get("url") or ""),
        str(candidate.url or ""),
        str(candidate.filename or ""),
        str(candidate.reason or ""),
    ]).lower()
    if "interfax" in haystack or "интерфакс" in haystack:
        return True
    bad_markers = ["ogimage", "og_image", "og-image", "social-card", "share-card", "preview-card", "twitter-card"]
    return any(marker in haystack for marker in bad_markers)


def story_image_mismatch(article: dict, candidate) -> str | None:
    if not candidate or getattr(candidate, "source", "") == "generated":
        return None
    a = article_words(article)
    c = candidate_words(candidate)

    banned_visual = [
        "postage", "stamp", "stamps", "postal", "philately", "souvenir sheet", "commemorative",
        "postcard", "марка", "почтов", "poster", "flyer", "infographic", "title card", "text card",
        "social card", "og-image", "ogimage", "logo", "icon", "avatar", "placeholder", "banner"
    ]
    if has_any(c, banned_visual):
        return "banned visual type, not a normal news photo"

    rules = [
        {
            "name": "us_iran_diplomacy",
            "article": ["трамп", "trump", "иран", "iran", "тегеран", "tehran", "авраам", "abraham"],
            "must": ["trump", "iran", "tehran", "usa", "united states", "washington", "israel", "abraham", "accord", "agreement", "talks", "diplomacy", "middle east", "saudi", "qatar", "uae", "bahrain", "arab", "islamic"],
            "deny": ["uzbekistan", "o'zbekiston", "ukraine", "irena", "renewable", "spacecraft", "chip", "server"],
        },
        {
            "name": "spaceflight",
            "article": ["шэньчжоу", "shenzhou", "тяньгун", "tiangong", "тайконавт", "taikonaut", "астронавт", "orbit", "орбит", "spacecraft", "space station", "cmsa"],
            "must": ["space", "spacecraft", "station", "orbit", "rocket", "astronaut", "taikonaut", "shenzhou", "tiangong", "cmsa", "космос", "орбит", "станц", "тайконавт", "шэньчжоу", "тяньгун"],
            "deny": ["summit", "conference", "chip", "server", "game", "bank"],
        },
        {
            "name": "snow_rescue",
            "article": ["лавина", "сход лавины", "спасатели", "пропали", "пропавшие", "горы", "снег", "поисково-спас"],
            "must": ["avalanche", "snow", "mountain", "rescue", "search", "winter", "лавина", "горы", "снег", "спасатели"],
            "deny": ["chip", "server", "processor", "circuit", "pipeline", "game"],
        },
        {
            "name": "water_repair",
            "article": ["водопровод", "водоснаб", "без воды", "коллектор", "труба", "коммуналь", "жкх"],
            "must": ["water", "pipe", "pipeline", "plumbing", "repair", "utility", "municipal", "вод", "труб", "водопровод"],
            "deny": ["road", "car", "vehicle", "chip", "server", "game"],
        },
    ]
    for rule in rules:
        if has_any(a, rule["article"]):
            if has_any(c, rule["deny"]):
                return f"image conflicts with story topic: {rule['name']}"
            if not has_any(c, rule["must"]):
                return f"no positive story-level image match: {rule['name']}"
    return None


def resolve_generated_only(article: dict, state: dict, prefix: str):
    generated, attempts = generated_candidate(article, state, logger=log)
    if generated:
        return ImageDecision(generated, "generated", prefix + "; generated semantic image accepted", attempts)
    return ImageDecision(None, "none", prefix + "; generated replacement failed", attempts)


def resolve_without_source(article: dict, state: dict):
    attempts = []
    searched, a = external_thematic_search(article, state, logger=log)
    attempts.extend(a)
    if searched:
        return ImageDecision(searched, "search", "source text-card rejected; external thematic image accepted", attempts)
    generated, a = generated_candidate(article, state, logger=log)
    attempts.extend(a)
    if generated:
        return ImageDecision(generated, "generated", "source text-card rejected; generated semantic image accepted", attempts)
    return ImageDecision(None, "none", "source text-card rejected; no valid replacement image found", attempts)


def resolve_image_file(draft: dict, state: dict):
    if draft.get("image_decision") == "drop":
        return None, None

    article = article_for_image(draft)
    decision = resolve_article_image(article, state, logger=log)

    if decision.selected and is_forbidden_source_text_card(article, decision.selected):
        log("image source rejected as text/title card: " + str(decision.selected.url)[:160])
        replacement = resolve_without_source(article, state)
        replacement.attempts = decision.attempts + replacement.attempts
        decision = replacement

    mismatch = story_image_mismatch(article, decision.selected)
    if mismatch:
        log("image rejected by final story guard: " + mismatch)
        replacement = resolve_generated_only(article, state, "final story guard rejected image: " + mismatch)
        replacement.attempts = decision.attempts + replacement.attempts
        decision = replacement

    draft["image_pipeline"] = decision_to_dict(decision)

    if not decision.selected:
        draft["status"] = "hold"
        draft.setdefault("editor_notes", []).append("Safe publisher: нет валидного изображения после source/search/generate; публикация остановлена.")
        return None, decision

    candidate = decision.selected
    image_file = candidate_to_file(candidate)
    if not image_file:
        draft["status"] = "hold"
        draft.setdefault("editor_notes", []).append("Safe publisher: image pipeline вернул кандидата без данных; публикация остановлена.")
        return None, decision

    draft["image_mode"] = f"pipeline_{decision.strategy}"
    draft["image_url"] = candidate.url
    draft["with_image"] = True
    draft["image_decision"] = "use"
    draft["image_fingerprint"] = bytes_fingerprint(candidate.data)
    draft.setdefault("editor_notes", []).append(
        f"Image pipeline: {decision.strategy}; {decision.reason}; score={candidate.relevance_score:.2f}."
    )
    remember_image_in_state(state, candidate)
    return image_file, decision


def publish_safe() -> None:
    state = q.b.load_state()
    queue = q.load_queue()
    q.reject_stale(queue)

    published = 0
    published_urls = set(state.get("published_urls", []) or [])

    for draft in queue.get("items", []) or []:
        if published >= q.PUBLISH_LIMIT:
            break
        if draft.get("status") != "approved":
            continue

        if draft.get("url") in published_urls:
            draft["status"] = "published"
            draft.setdefault("editor_notes", []).append("Уже опубликовано ранее по URL.")
            continue

        text = draft.get("edited_post_text") or draft.get("post_text") or ""
        if not text.strip():
            draft["status"] = "hold"
            draft.setdefault("editor_notes", []).append("Safe publisher: нет текста для публикации.")
            continue

        image_file, decision = resolve_image_file(draft, state)
        if not image_file:
            log("safe publisher hold: no valid image for " + str(draft.get("title_ru") or draft.get("title_original"))[:120])
            continue

        try:
            item = q.item_for_publish(draft, image_file=image_file)
            caption = text[:980]
            log(
                f"safe publish image-card [{draft.get('image_mode')}]: "
                f"{draft.get('category')} | {draft.get('source')} | {str(draft.get('title_ru') or '')[:90]}"
            )
            result = q.b.tg_photo(item, caption)
            method = f"sendPhoto/safe/{draft.get('image_mode') or 'image'}"
        except Exception as exc:
            draft.setdefault("editor_notes", []).append("Safe publisher error: " + str(exc))
            log("safe publisher failed: " + str(exc))
            continue

        if result and result.get("ok"):
            draft["status"] = "published"
            draft["published_at_sakhalin"] = q.now_sakh()
            draft["publish_method"] = method
            message_id = q.extract_message_id(result)
            if message_id:
                draft["telegram_message_id"] = message_id

            state.setdefault("published_urls", []).append(draft.get("url"))
            if draft.get("title_hash"):
                state.setdefault("published_title_hashes", []).append(draft.get("title_hash"))
            state.setdefault("last_posts", []).append({
                "time_sakhalin": datetime.now(q.b.TZ).isoformat(timespec="seconds"),
                "source": draft.get("source"),
                "category": draft.get("category"),
                "title": draft.get("title_ru") or draft.get("title_original"),
                "url": draft.get("url"),
                "published_at": draft.get("published_at"),
                "with_image": True,
                "image_mode": draft.get("image_mode"),
                "image_url": draft.get("image_url"),
                "image_fingerprint": draft.get("image_fingerprint"),
                "publish_method": method,
                "telegram_message_id": message_id,
                "score": draft.get("score"),
            })
            published += 1
            time.sleep(12)

    q.b.save_state(state)
    q.save_queue(queue)
    log(f"Safe publisher: published={published}")


if __name__ == "__main__":
    publish_safe()
