import time
from datetime import datetime

import editorial_queue as q
from image_pipeline import (
    candidate_to_file,
    decision_to_dict,
    remember_image_in_state,
    resolve_article_image,
    bytes_fingerprint,
)


def log(message: str) -> None:
    try:
        q.b.log(message)
    except Exception:
        print(message)


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
    })
    return item


def resolve_image_file(draft: dict, state: dict):
    if draft.get("image_decision") == "drop":
        return None, None

    article = article_for_image(draft)
    decision = resolve_article_image(article, state, logger=log)
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
