# Post-publication audit for SkySakhNews.
# Reads full published post payloads from state.json after publishing and builds an audit report.
# The audit is intentionally conservative: it reports defects first; deletion is disabled by default.
# Audit reports are sent only to a private admin chat configured by TELEGRAM_AUDIT_CHAT_ID/ADMIN_CHAT_ID.

import difflib
import html
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List

import requests

STATE_FILE = Path("state.json")
QUEUE_FILE = Path("editorial_queue.json")
AUDIT_FILE = Path("post_publish_audit_report.json")
SAKH_TZ = timezone(timedelta(hours=11))

DELETE_BAD_POSTS = os.getenv("DELETE_BAD_POSTS", "0") == "1"
SEND_AUDIT_TO_TELEGRAM = os.getenv("SEND_AUDIT_TO_TELEGRAM", "1") == "1"
AUDIT_RECENT_LIMIT = int(os.getenv("POST_AUDIT_RECENT_LIMIT", "8"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
TELEGRAM_AUDIT_CHAT_ID = (
    os.getenv("TELEGRAM_AUDIT_CHAT_ID", "").strip()
    or os.getenv("ADMIN_CHAT_ID", "").strip()
    or os.getenv("AUDIT_CHAT_ID", "").strip()
)

PURE_BPLA_TERMS = [
    "уничтожен", "уничтожены", "сбит", "сбиты", "сбито", "перехвачен", "перехвачены",
    "нейтрализован", "нейтрализованы", "ликвидации бпла", "над территорией", "над областью",
    "над регионом", "за ночь уничтожены", "за ночь сбиты"
]
REAL_IMPACT_TERMS = [
    "погиб", "погибли", "скончал", "ранен", "ранены", "пострадал", "пострадали", "жертвы",
    "поврежден", "повреждены", "повреждена", "разрушен", "разрушены", "пожар", "возгорание",
    "ущерб", "эвакуац", "обесточ", "без электричества", "без света", "отключени", "попадание",
    "прилет", "прилёт", "атаковал автомобиль", "атаковали автомобиль"
]
PROPAGANDA_PHRASES = ["беззащитным детям", "каратели", "нацисты", "террористический режим", "прицельно ударили по спящим"]
BANNED_IMAGE_CLUES = [
    "stamp", "postage", "postal", "philately", "souvenir sheet", "commemorative", "postcard",
    "марка", "почтов", "poster", "flyer", "infographic", "title card", "text card", "social card",
    "og-image", "ogimage", "logo", "icon", "avatar", "placeholder", "banner"
]

REQUIRED_IMAGE_RULES = [
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


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_sakh() -> str:
    return datetime.now(SAKH_TZ).isoformat(timespec="seconds")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm(value: str) -> str:
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value.lower().replace("ё", "е")).strip()


def clean_preview(value: str, limit: int = 700) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def has_any(text: str, terms: List[str]) -> bool:
    text = norm(text)
    return any(norm(t) in text for t in terms)


def sim_norm(text: str) -> str:
    text = norm(text)
    text = re.sub(r'"[^"\n]{0,260}"', ' ', text)
    text = re.sub(r'\b(сообщил[аи]?|заявил[аи]?|написал[аи]?|уточнил[аи]?|добавил[аи]?|по данным|по словам|в оперштабе|в региональном оперштабе|губернатор[^.]{0,80})\b', ' ', text)
    text = re.sub(r'[^a-zа-я0-9 ]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def too_similar(a: str, b: str) -> bool:
    aa, bb = sim_norm(a), sim_norm(b)
    if not aa or not bb:
        return False
    ratio = difflib.SequenceMatcher(None, aa, bb).ratio()
    wa, wb = set(aa.split()), set(bb.split())
    jaccard = len(wa & wb) / max(1, len(wa | wb))
    return ratio >= 0.74 or jaccard >= 0.62


def body_paragraphs(caption: str) -> List[str]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", caption or "") if p.strip()]
    out = []
    for part in parts:
        p = norm(part)
        if p.startswith(("🇷🇺", "🌍", "🧭", "🌐", "🎮", "📍")):
            continue
        if "interfax" in p and "·" in p:
            continue
        out.append(part)
    return out


def duplicate_text_issues(post: Dict) -> List[str]:
    issues = []
    pars = body_paragraphs(post.get("caption_plain") or post.get("caption") or "")
    if len(pars) >= 2:
        for i, a in enumerate(pars):
            for b in pars[i + 1:]:
                if too_similar(a, b):
                    issues.append("semantic_duplicate_paragraphs")
                    return issues
    return issues


def weak_bpla_issues(post: Dict) -> List[str]:
    text = norm(" ".join([post.get("title") or "", post.get("caption_plain") or post.get("caption") or ""]))
    if has_any(text, ["бпла", "беспилотник", "беспилотники", "дрон", "дроны"]):
        if has_any(text, PURE_BPLA_TERMS) and not has_any(text, REAL_IMPACT_TERMS):
            return ["weak_bpla_without_impact"]
    return []


def image_issues(post: Dict) -> List[str]:
    issues = []
    pipeline = post.get("image_pipeline") or {}
    selected = pipeline.get("selected") or {}
    selected_text = norm(" ".join([
        str(post.get("image_mode") or ""),
        str(post.get("image_url") or ""),
        str(selected.get("url") or ""),
        str(selected.get("filename") or ""),
        str(selected.get("query_used") or ""),
        str(selected.get("reason") or ""),
    ]))
    article_text = norm(" ".join([post.get("category") or "", post.get("title") or "", post.get("caption_plain") or post.get("caption") or ""]))
    if has_any(selected_text, BANNED_IMAGE_CLUES):
        issues.append("banned_visual_type")
    for rule in REQUIRED_IMAGE_RULES:
        if has_any(article_text, rule["article"]):
            if has_any(selected_text, rule["deny"]):
                issues.append(f"image_conflicts_{rule['name']}")
            elif (post.get("image_mode") or "") != "pipeline_generated" and not has_any(selected_text, rule["must"]):
                issues.append(f"image_no_story_match_{rule['name']}")
    return issues


def propaganda_issues(post: Dict) -> List[str]:
    text = norm(post.get("caption_plain") or post.get("caption") or "")
    return ["propaganda_phrase"] if has_any(text, PROPAGANDA_PHRASES) else []


def audit_post(post: Dict) -> Dict:
    issues = []
    issues.extend(duplicate_text_issues(post))
    issues.extend(weak_bpla_issues(post))
    issues.extend(image_issues(post))
    issues.extend(propaganda_issues(post))
    status = "pass" if not issues else "fail"
    severity = "ok" if not issues else ("critical" if any(x in issues for x in ["weak_bpla_without_impact", "banned_visual_type"] or x.startswith("image_conflicts") for x in issues) else "warning")
    caption_plain = post.get("caption_plain") or post.get("caption") or ""
    return {
        "telegram_message_id": post.get("telegram_message_id"),
        "title": post.get("title"),
        "category": post.get("category"),
        "time_sakhalin": post.get("time_sakhalin"),
        "image_mode": post.get("image_mode"),
        "image_url": post.get("image_url"),
        "url": post.get("url"),
        "status": status,
        "severity": severity,
        "issues": issues,
        "content_preview": clean_preview(caption_plain, 900),
    }


def tg_request(method: str, payload: Dict) -> Dict:
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN missing"}
    try:
        resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}", json=payload, timeout=20)
        try:
            return resp.json()
        except Exception:
            return {"ok": False, "description": resp.text[:500]}
    except Exception as exc:
        return {"ok": False, "description": str(exc)}


def delete_bad_post(message_id: int) -> Dict:
    if not message_id or not TELEGRAM_CHANNEL_ID:
        return {"ok": False, "description": "missing message_id or chat_id"}
    return tg_request("deleteMessage", {"chat_id": TELEGRAM_CHANNEL_ID, "message_id": message_id})


def send_audit_report(report: Dict) -> Dict:
    if not SEND_AUDIT_TO_TELEGRAM:
        return {"ok": False, "description": "audit telegram report disabled"}
    if not TELEGRAM_AUDIT_CHAT_ID:
        return {"ok": False, "description": "TELEGRAM_AUDIT_CHAT_ID/ADMIN_CHAT_ID missing; not sending report to public channel"}
    failed = [x for x in report.get("items", []) if x.get("status") == "fail"]
    passed = [x for x in report.get("items", []) if x.get("status") == "pass"]
    lines = [
        "🧪 <b>SkySakhNews post-publish audit</b>",
        f"Проверено: {len(report.get('items', []))}; OK: {len(passed)}; FAIL: {len(failed)}",
        f"Время: {report.get('checked_at_sakhalin')}",
    ]
    shown = report.get("items", [])[:6]
    if shown:
        lines.append("")
        for item in shown:
            mark = "✅" if item.get("status") == "pass" else "❌"
            title = html.escape(str(item.get("title") or "")[:120])
            issues = ", ".join(item.get("issues") or ["ok"])
            preview = html.escape(str(item.get("content_preview") or "")[:420])
            lines.append(f"{mark} <b>{title}</b>")
            lines.append(f"ID: <code>{item.get('telegram_message_id')}</code>; issues: <code>{html.escape(issues)}</code>; image: <code>{html.escape(str(item.get('image_mode') or ''))}</code>")
            lines.append(f"<blockquote>{preview}</blockquote>")
    else:
        lines.append("\nПостов для аудита нет.")
    return tg_request("sendMessage", {"chat_id": TELEGRAM_AUDIT_CHAT_ID, "text": "\n".join(lines)[:3900], "parse_mode": "HTML", "disable_web_page_preview": True})


def main() -> None:
    state = load_json(STATE_FILE, {})
    posts = list(state.get("last_posts", []) or [])[-AUDIT_RECENT_LIMIT:]
    targets = [p for p in posts if p.get("telegram_message_id") and p.get("audit_status") in {None, "pending"}]
    items = []
    deleted = []
    for post in targets:
        result = audit_post(post)
        post["audit_status"] = result["status"]
        post["audit_severity"] = result["severity"]
        post["audit_issues"] = result["issues"]
        post["audited_at"] = now_utc()
        post["audited_at_sakhalin"] = now_sakh()
        if DELETE_BAD_POSTS and result["severity"] == "critical":
            delete_result = delete_bad_post(post.get("telegram_message_id"))
            post["delete_result"] = delete_result
            deleted.append({"message_id": post.get("telegram_message_id"), "ok": delete_result.get("ok"), "title": post.get("title")})
        items.append(result)

    report = {
        "version": 2,
        "checked_at": now_utc(),
        "checked_at_sakhalin": now_sakh(),
        "checked_count": len(items),
        "failed_count": len([x for x in items if x.get("status") == "fail"]),
        "audit_chat_configured": bool(TELEGRAM_AUDIT_CHAT_ID),
        "delete_bad_posts": DELETE_BAD_POSTS,
        "deleted": deleted,
        "items": items,
    }
    state["last_post_publish_audit"] = report
    save_json(STATE_FILE, state)
    save_json(AUDIT_FILE, report)
    send_result = send_audit_report(report) if items else {"ok": False, "description": "nothing to audit"}
    print(f"post-publish-audit-v2: checked={len(items)}, failed={report['failed_count']}, audit_chat_configured={bool(TELEGRAM_AUDIT_CHAT_ID)}, delete_bad_posts={DELETE_BAD_POSTS}, report_sent={send_result.get('ok')}")
    if not send_result.get("ok"):
        print("audit-report-send-note: " + str(send_result.get("description")))
    if items:
        for item in items:
            print(json.dumps(item, ensure_ascii=False))


if __name__ == "__main__":
    main()
