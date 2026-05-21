# SkySakhNews cycle execution report.
# Runs at the end of Editorial Cycle and records a clear machine-readable summary:
# collected/reviewed/guarded/published status, queue distribution and recent publications.

import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE_FILE = ROOT / "editorial_queue.json"
STATE_FILE = ROOT / "state.json"
REPORT_FILE = ROOT / "cycle_report.json"
SAKH_TZ = timezone(timedelta(hours=11))


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_sakh() -> str:
    return datetime.now(SAKH_TZ).isoformat(timespec="seconds")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def recent_posts(state: dict, minutes: int = 20) -> list[dict]:
    cutoff = datetime.now(SAKH_TZ) - timedelta(minutes=minutes)
    out = []
    for post in state.get("last_posts", []) or []:
        dt = parse_dt(post.get("time_sakhalin"))
        if not dt:
            continue
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=SAKH_TZ)
        if dt.astimezone(SAKH_TZ) >= cutoff:
            out.append(post)
    return out[-10:]


def status_counts(items: list[dict]) -> dict:
    counts = Counter(str(item.get("status") or "unknown") for item in items)
    for key in ["pending", "approved", "hold", "rejected", "published", "skipped", "unknown"]:
        counts.setdefault(key, 0)
    return dict(counts)


def category_counts(items: list[dict], status: str | None = None) -> dict:
    filtered = [x for x in items if status is None or x.get("status") == status]
    counts = Counter(str(x.get("category") or x.get("category_hint") or "unknown") for x in filtered)
    return dict(counts.most_common())


def main() -> None:
    queue = load_json(QUEUE_FILE, {"version": 1, "items": []})
    state = load_json(STATE_FILE, {})
    items = queue.get("items", []) or []
    recent = recent_posts(state, minutes=20)

    counts = status_counts(items)
    report = {
        "reported_at": now_utc(),
        "reported_at_sakhalin": now_sakh(),
        "queue_updated_at": queue.get("updated_at"),
        "queue_updated_at_sakhalin": queue.get("updated_at_sakhalin"),
        "total_queue_items": len(items),
        "status_counts": counts,
        "hold_by_category": category_counts(items, status="hold"),
        "approved_by_category": category_counts(items, status="approved"),
        "published_by_category": category_counts(items, status="published"),
        "auto_review": queue.get("auto_review", {}),
        "priority_guard": queue.get("priority_guard", {}),
        "final_guard": queue.get("final_guard", {}),
        "recent_published_20m_count": len(recent),
        "recent_published_20m": [
            {
                "time_sakhalin": p.get("time_sakhalin"),
                "source": p.get("source"),
                "category": p.get("category"),
                "title": p.get("title"),
                "with_image": p.get("with_image"),
                "image_mode": p.get("image_mode"),
                "publish_method": p.get("publish_method"),
                "telegram_message_id": p.get("telegram_message_id"),
            }
            for p in recent
        ],
        "decision": (
            "published" if recent else
            "no_approved_to_publish" if counts.get("approved", 0) == 0 else
            "approved_left_unpublished_check_publish_step"
        ),
    }

    queue["cycle_report"] = report
    state["last_cycle_report"] = report
    save_json(QUEUE_FILE, queue)
    save_json(STATE_FILE, state)
    save_json(REPORT_FILE, report)

    print("SKYSAKHNEWS_CYCLE_REPORT")
    print(f"reported_at_sakhalin={report['reported_at_sakhalin']}")
    print(f"queue_items={report['total_queue_items']}")
    print("status_counts=" + json.dumps(report["status_counts"], ensure_ascii=False, sort_keys=True))
    print("auto_review=" + json.dumps(report["auto_review"], ensure_ascii=False, sort_keys=True))
    print("priority_guard=" + json.dumps(report["priority_guard"], ensure_ascii=False, sort_keys=True))
    print("final_guard=" + json.dumps(report["final_guard"], ensure_ascii=False, sort_keys=True))
    print(f"recent_published_20m_count={report['recent_published_20m_count']}")
    print(f"decision={report['decision']}")
    print("SYSTEM_CYCLE_REPORT_OK")


if __name__ == "__main__":
    main()
