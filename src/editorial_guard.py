import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

QUEUE_FILE = Path('editorial_queue.json')
SAKH_TZ = timezone(timedelta(hours=11))

LOW_PRIORITY_GAME_SOURCES = {'GameSpot', 'IGN', 'Eurogamer', 'PC Gamer'}
BAD_URL_MARKERS = [
    'nvidia.com/en-us/drivers',
    'amazon.',
    'walmart.',
    'woot.com',
]
BAD_TEXT_MARKERS = [
    'download the latest',
    'official nvidia drivers',
    'lowest price',
    'free shipping',
    'prime members',
    'less than $',
    'under $',
    'deal',
    'sale',
    'discount',
    'coupon',
    'power bank',
]


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def now_sakh():
    return datetime.now(SAKH_TZ).isoformat(timespec='seconds')


def load_queue():
    if not QUEUE_FILE.exists():
        return {'version': 1, 'items': []}
    try:
        return json.loads(QUEUE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {'version': 1, 'items': []}


def save_queue(q):
    q['updated_at'] = now_utc()
    q['updated_at_sakhalin'] = now_sakh()
    QUEUE_FILE.write_text(json.dumps(q, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def cyrillic_ratio(text):
    letters = re.findall(r'[A-Za-zА-Яа-яЁё]', text or '')
    if not letters:
        return 0.0
    cyr = re.findall(r'[А-Яа-яЁё]', text or '')
    return len(cyr) / max(1, len(letters))


def blob(item):
    return ' '.join(str(item.get(k) or '') for k in ['title_ru', 'title_original', 'post_text', 'edited_post_text', 'source_text', 'url', 'source']).lower()


def fail(item, reason):
    item['status'] = 'rejected'
    item['reviewed_at'] = now_utc()
    item['reviewed_by'] = 'final-guard'
    item.setdefault('editor_notes', []).append(reason)
    if any(x in blob(item) for x in BAD_TEXT_MARKERS + BAD_URL_MARKERS):
        item['image_decision'] = 'drop'


def main():
    q = load_queue()
    changed = 0
    for item in q.get('items', []) or []:
        if item.get('status') != 'approved':
            continue
        text = item.get('edited_post_text') or item.get('post_text') or ''
        b = blob(item)
        if any(x in b for x in BAD_URL_MARKERS + BAD_TEXT_MARKERS):
            fail(item, 'Финальный стоп: рекламный/товарный/служебный материал, не новость.')
            changed += 1
            continue
        if cyrillic_ratio(text) < 0.45:
            fail(item, 'Финальный стоп: approved-пост не русифицирован, публикация запрещена.')
            changed += 1
            continue
        if item.get('category') == '🎮 Игры / индустрия' and item.get('source') in LOW_PRIORITY_GAME_SOURCES:
            fail(item, 'Финальный стоп: игровые новости публикуются только после ручного высокого приоритета; источник низкого приоритета.')
            changed += 1
            continue
    q['final_guard'] = {'changed': changed, 'checked_at': now_utc(), 'checked_at_sakhalin': now_sakh()}
    save_queue(q)
    print(f'final-guard: changed={changed}')


if __name__ == '__main__':
    main()
