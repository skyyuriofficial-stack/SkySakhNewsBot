# Editorial queue for SkySakhNews.
# Modes:
#   collect      -> collect raw/editorial candidates into editorial_queue.json, do not publish
#   publish      -> publish only items approved in editorial_queue.json
#   reject-stale -> reject old pending items
#
# Important design rule:
# collect mode must NOT depend on OpenRouter generation. The queue is for human/ChatGPT
# editorial review, so candidates must be saved even when the free OpenRouter quota is exhausted.

import json
import os
import sys
import hashlib
import re
import html
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional

import news_bot_v14 as v14

b = v14.b

QUEUE_FILE = Path("editorial_queue.json")
QUEUE_LIMIT = 160
COLLECT_LIMIT = int(os.getenv("EDITORIAL_COLLECT_LIMIT", "12"))
PUBLISH_LIMIT = int(os.getenv("EDITORIAL_PUBLISH_LIMIT", "2"))
PENDING_TTL_HOURS = int(os.getenv("EDITORIAL_PENDING_TTL_HOURS", "18"))


def now_sakh() -> str:
    return datetime.now(b.TZ).isoformat(timespec="seconds")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_queue() -> Dict:
    q = load_json(QUEUE_FILE, {})
    if not isinstance(q, dict):
        q = {}
    q.setdefault("version", 1)
    q.setdefault("updated_at", now_utc())
    q.setdefault("items", [])
    return q


def save_queue(q: Dict) -> None:
    q["updated_at"] = now_utc()
    q["updated_at_sakhalin"] = now_sakh()
    items = q.get("items", []) or []
    priority = {"pending": 0, "approved": 1, "hold": 2, "rejected": 3, "published": 4, "skipped": 5}
    items.sort(key=lambda x: (priority.get(x.get("status"), 9), x.get("created_at", "")), reverse=False)
    q["items"] = items[-QUEUE_LIMIT:]
    save_json(QUEUE_FILE, q)


def clean(value) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def esc(value) -> str:
    return html.escape(str(value or ""), quote=False)


def attr(value) -> str:
    return html.escape(str(value or ""), quote=True)


def draft_id(url: str) -> str:
    return hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:16]


def short_sentences(text: str, limit: int = 4):
    text = clean(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+|(?<=\.)\s+", text)
    out = []
    for part in parts:
        part = clean(part)
        if len(part) < 35:
            continue
        out.append(part[:420])
        if len(out) >= limit:
            break
    if not out and text:
        out = [text[:420]]
    return out


def raw_post_text(item: Dict) -> str:
    category = clean(item.get("category_hint") or "НОВОСТИ")
    title = clean(item.get("title") or "")
    source = clean(item.get("source") or "Источник")
    url = attr(item.get("url") or "")
    footer = clean(getattr(b, "FOOTER", {}).get(category, category.upper())) if hasattr(b, "FOOTER") else category.upper()

    body = short_sentences(item.get("summary") or "", limit=3)
    body_text = "\n\n".join(esc(x) for x in body)
    if body_text:
        return f"{esc(category)}\n\n<b>{esc(title)}</b>\n\n{body_text}\n\n{esc(footer)} · <a href=\"{url}\">{esc(source)}</a>"
    return f"{esc(category)}\n\n<b>{esc(title)}</b>\n\n{esc(footer)} · <a href=\"{url}\">{esc(source)}</a>"


def compact_item(item: Dict, post_text: str, image_file, image_mode: str, image_url: Optional[str]) -> Dict:
    title = clean(item.get("title"))
    return {
        "id": draft_id(item["url"]),
        "status": "pending",
        "created_at": now_utc(),
        "created_at_sakhalin": now_sakh(),
        "source": item.get("source"),
        "source_type": item.get("source_type"),
        "category": item.get("category_hint"),
        "category_hint": item.get("category_hint"),
        "score": item.get("score"),
        "title_original": title,
        "title_ru": title,
        "body": short_sentences(item.get("summary") or "", limit=3),
        "footer": None,
        "source_text": item.get("summary"),
        "post_text": post_text,
        "edited_post_text": None,
        "url": item.get("url"),
        "published_at": item.get("published_at"),
        "title_hash": item.get("title_hash"),
        "image_url": image_url,
        "image_mode": image_mode,
        "with_image": bool(image_file),
        "image_decision": "use" if image_file else "none",
        "editor_notes": [
            "Черновик сохранён без OpenRouter-генерации: требуется редакторская проверка/правка перед approved."
        ],
        "review": {
            "required": True,
            "reviewer": "ChatGPT/editor",
            "instruction": "Approve only after checking: one concrete fresh news item, correct category, factual Russian post text, no mixed digest, no low-value ad/deal/tutorial, image relevant or image_decision=drop. If edited, fill edited_post_text."
        },
    }


def existing_keys(queue: Dict) -> set:
    keys = set()
    for x in queue.get("items", []) or []:
        if x.get("url"):
            keys.add(x["url"])
        if x.get("id"):
            keys.add(x["id"])
    return keys


def is_old_pending(item: Dict) -> bool:
    if item.get("status") != "pending":
        return False
    raw = item.get("created_at")
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - dt.astimezone(timezone.utc) > timedelta(hours=PENDING_TTL_HOURS)
    except Exception:
        return False


def reject_stale(queue: Dict) -> int:
    count = 0
    for item in queue.get("items", []) or []:
        if is_old_pending(item):
            item["status"] = "rejected"
            item.setdefault("editor_notes", []).append("Автоотклонено: черновик устарел в редакторской очереди.")
            item["reviewed_at"] = now_utc()
            item["reviewed_by"] = "system"
            count += 1
    return count


def source_image_only(item: Dict):
    image_file = item.get("image_file")
    image_url = item.get("image_url")
    if image_file and image_url:
        return image_file, "source", image_url
    return None, "none", None


def collect_to_queue() -> None:
    state = b.load_state()
    queue = load_queue()
    rejected_stale = reject_stale(queue)
    keys = existing_keys(queue)
    published_urls = set(state.get("published_urls", []) or [])
    published_titles = set(state.get("published_title_hashes", []) or [])

    b.log("Editorial queue: collecting candidates")
    items = b.collect(state)
    ordered = b.select_order(items)
    added = 0

    for item in ordered:
        if added >= COLLECT_LIMIT:
            break
        if item.get("url") in published_urls or item.get("title_hash") in published_titles:
            continue
        if item.get("url") in keys or draft_id(item.get("url")) in keys:
            continue
        try:
            image_file, image_mode, image_url = source_image_only(item)
            post_text = raw_post_text(item)
            draft = compact_item(item, post_text, image_file, image_mode, image_url)
            queue.setdefault("items", []).append(draft)
            keys.add(draft["url"])
            keys.add(draft["id"])
            added += 1
            b.log(f"queued raw: {draft['category']} | {draft['source']} | {draft.get('title_ru') or draft.get('title_original')}")
        except Exception as exc:
            b.log("queue candidate skipped: " + str(exc))
            continue

    save_queue(queue)
    b.log(f"Editorial queue: added={added}, stale_rejected={rejected_stale}, total={len(queue.get('items', []))}")


def item_for_publish(draft: Dict, image_file=None) -> Dict:
    return {
        "source": draft.get("source"),
        "category_hint": draft.get("category") or draft.get("category_hint"),
        "title": draft.get("title_original") or draft.get("title_ru"),
        "summary": draft.get("source_text") or "",
        "url": draft.get("url"),
        "image_url": draft.get("image_url"),
        "image_file": image_file,
        "published_at": draft.get("published_at"),
        "title_hash": draft.get("title_hash"),
        "score": draft.get("score"),
    }


def fetch_queue_image(draft: Dict):
    if draft.get("image_decision") == "drop":
        return None
    url = draft.get("image_url")
    if not url:
        return None
    return b.fetch_image_bytes(url)


def publish_approved() -> None:
    state = b.load_state()
    queue = load_queue()
    rejected_stale = reject_stale(queue)

    published = 0
    for draft in queue.get("items", []) or []:
        if published >= PUBLISH_LIMIT:
            break
        if draft.get("status") != "approved":
            continue
        if draft.get("url") in set(state.get("published_urls", []) or []):
            draft["status"] = "published"
            draft.setdefault("editor_notes", []).append("Уже опубликовано ранее по URL.")
            continue

        try:
            text = draft.get("edited_post_text") or draft.get("post_text") or ""
            image_file = fetch_queue_image(draft)
            item = item_for_publish(draft, image_file=image_file)

            if image_file:
                caption = text[:980]
                b.log(f"publish approved image-card [{draft.get('image_mode')}]: {draft.get('category')} | {draft.get('source')} | {draft.get('title_ru')}")
                result = b.tg_photo(item, caption)
                method = f"sendPhoto/approved/{draft.get('image_mode') or 'image'}"
            else:
                b.log(f"publish approved text: {draft.get('category')} | {draft.get('source')} | {draft.get('title_ru')}")
                result = v14.v12.send_text_no_preview(text[:2600]) if hasattr(v14, 'v12') else None
                method = "sendMessage/approved/no-image"
        except Exception as exc:
            draft.setdefault("editor_notes", []).append("Ошибка публикации: " + str(exc))
            b.log("approved publish failed: " + str(exc))
            continue

        if result and result.get("ok"):
            draft["status"] = "published"
            draft["published_at_sakhalin"] = now_sakh()
            draft["publish_method"] = method
            state.setdefault("published_urls", []).append(draft.get("url"))
            if draft.get("title_hash"):
                state.setdefault("published_title_hashes", []).append(draft.get("title_hash"))
            state.setdefault("last_posts", []).append({
                "time_sakhalin": now_sakh(),
                "source": draft.get("source"),
                "category": draft.get("category"),
                "title": draft.get("title_ru") or draft.get("title_original"),
                "url": draft.get("url"),
                "published_at": draft.get("published_at"),
                "with_image": bool(image_file),
                "image_mode": draft.get("image_mode") if image_file else "none",
                "image_url": draft.get("image_url") if image_file else None,
                "publish_method": method,
                "score": draft.get("score"),
            })
            published += 1
            time.sleep(12)

    b.save_state(state)
    save_queue(queue)
    b.log(f"Editorial queue: published={published}, stale_rejected={rejected_stale}")


def print_queue_summary() -> None:
    q = load_queue()
    counts = {}
    for item in q.get("items", []) or []:
        counts[item.get("status", "unknown")] = counts.get(item.get("status", "unknown"), 0) + 1
    b.log("Editorial queue summary: " + json.dumps(counts, ensure_ascii=False))


def main() -> None:
    mode = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("EDITORIAL_MODE", "collect")).strip().lower()
    if mode == "collect":
        collect_to_queue()
    elif mode == "publish":
        publish_approved()
    elif mode == "reject-stale":
        q = load_queue()
        count = reject_stale(q)
        save_queue(q)
        b.log(f"Stale pending rejected: {count}")
    elif mode == "summary":
        print_queue_summary()
    else:
        raise SystemExit("Unknown editorial_queue mode: " + mode)


if __name__ == "__main__":
    main()
