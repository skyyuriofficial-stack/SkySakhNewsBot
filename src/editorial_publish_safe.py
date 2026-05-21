import time
from datetime import datetime

import editorial_queue as q
from thematic_image import generate_thematic_image

SOURCE_MODES = {"source", "source_image", "rss_source", "page_source"}


def source_image_for(draft):
    if draft.get("image_decision") == "drop":
        return None
    mode = (draft.get("image_mode") or "").strip()
    url = draft.get("image_url")
    if not url or mode not in SOURCE_MODES:
        return None
    image = q.b.fetch_image_bytes(url)
    if not image:
        q.b.log("source image failed, using generated semantic image: " + str(url)[:120])
        return None
    draft["image_mode"] = "source"
    draft["with_image"] = True
    draft["image_decision"] = "use"
    return image


def generated_image_for(draft):
    data, content_type, filename = generate_thematic_image(draft)
    draft["image_mode"] = "generated_semantic"
    draft["image_url"] = None
    draft["with_image"] = True
    draft["image_decision"] = "use"
    draft.setdefault("editor_notes", []).append(
        "Safe publisher: source-картинка отсутствует или непригодна; создана локальная семантическая иллюстрация по тексту новости."
    )
    return data, content_type, filename


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

        image_file = source_image_for(draft)
        if not image_file:
            q.b.log("safe publisher generated semantic image: " + str(draft.get("title_ru") or draft.get("title_original"))[:120])
            image_file = generated_image_for(draft)

        try:
            item = q.item_for_publish(draft, image_file=image_file)
            caption = text[:980]
            q.b.log(
                f"safe publish image-card [{draft.get('image_mode')}]: "
                f"{draft.get('category')} | {draft.get('source')} | {str(draft.get('title_ru') or '')[:90]}"
            )
            result = q.b.tg_photo(item, caption)
            method = f"sendPhoto/safe/{draft.get('image_mode') or 'image'}"
        except Exception as exc:
            draft.setdefault("editor_notes", []).append("Safe publisher error: " + str(exc))
            q.b.log("safe publisher failed: " + str(exc))
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
                "publish_method": method,
                "telegram_message_id": message_id,
                "score": draft.get("score"),
            })
            published += 1
            time.sleep(12)

    q.b.save_state(state)
    q.save_queue(queue)
    q.b.log(f"Safe publisher: published={published}")


if __name__ == "__main__":
    publish_safe()
