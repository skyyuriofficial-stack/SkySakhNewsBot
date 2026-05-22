import html
import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

QUEUE_FILE = Path('editorial_queue.json')
SAKH_TZ = timezone(timedelta(hours=11))

LOW_PRIORITY_GAME_SOURCES = {'GameSpot', 'IGN', 'Eurogamer', 'PC Gamer'}
BAD_URL_MARKERS = ['nvidia.com/en-us/drivers', 'amazon.', 'walmart.', 'woot.com']
BAD_TEXT_MARKERS = [
    'download the latest', 'official nvidia drivers', 'lowest price', 'free shipping', 'prime members',
    'less than $', 'under $', 'deal', 'sale', 'discount', 'coupon', 'power bank'
]

FOOTERS = {
    '🌍 Мир о России': 'МИР О РОССИИ',
    '🇷🇺 РФ / война и безопасность': 'РФ | ВОЙНА И БЕЗОПАСНОСТЬ',
    '🇷🇺 РФ / происшествия': 'РФ | ПРОИСШЕСТВИЯ',
    '🇷🇺 РФ / экономика': 'РФ | ЭКОНОМИКА',
    '🇷🇺 РФ / законы и политика': 'РФ | ЗАКОНЫ И ПОЛИТИКА',
    '🧭 Геополитика': 'ГЕОПОЛИТИКА',
    '🌐 Мировые IT': 'МИРОВЫЕ IT',
    '🎮 Игры / индустрия': 'ИГРОВАЯ ИНДУСТРИЯ',
    '📍 Сахалин': 'САХАЛИН',
}

INCIDENT_TERMS = [
    'пожар', 'дтп', 'авария', 'аварии', 'утонул', 'утонули', 'погибли в результате пожара',
    'краж', 'мошеннич', 'убийств', 'нападение', 'обрушение', 'чп', 'происшеств'
]
MILITARY_TERMS = [
    'бпла', 'всу', 'пво', 'обстрел', 'удар', 'ракета', 'ракетный', 'дрон', 'дроны', 'минобороны',
    'фсб', 'теракт', 'диверс', 'заэс', 'аэс', 'фронт', 'военн', 'спецоперац'
]
ECON_TERMS = ['банк', 'кредит', 'ставк', 'цб', 'инфляц', 'нефть', 'газ', 'спг', 'рубл', 'экспорт', 'импорт', 'зерн']
POLITICS_TERMS = ['госдума', 'закон', 'сенат', 'правительство', 'переговор', 'визит', 'саммит', 'мид', 'путин', 'си цзиньпин']
GEOPOLITICS_TERMS = [
    'иран', 'израил', 'сша', 'нато', 'ес', 'китай', 'тайван', 'газа', 'оон', 'куба',
    'армения', 'армян', 'пашинян', 'ереван', 'антирассий', 'антироссий', 'россия и армения',
    'азербайджан', 'грузия', 'молдавия', 'молдова', 'постсоветск'
]
# Do not use generic Cyrillic "ии": it appears inside "России" and breaks geopolitics into IT.
IT_TERMS = [
    'openai', 'chatgpt', 'google ai', 'gemini', 'microsoft ai', 'anthropic', 'claude', 'nvidia',
    'apple intelligence', 'искусственный интеллект', 'нейросет', 'llm', 'gpt', 'cve', 'уязвим',
    'кибер', 'cyber', 'data center', 'server', 'software', 'чип', 'процессор'
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


def norm(text):
    return re.sub(r'\s+', ' ', str(text or '').lower().replace('ё', 'е')).strip()


def clean(text):
    text = html.unescape(str(text or ''))
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\bINTERFAX\.RU\s*-\s*', '', text)
    text = re.sub(r'\bМосква\.\s*\d+\s+[а-яА-Я]+\.\s*', '', text)
    text = re.sub(r'\s+', ' ', text).strip(' -—')
    return text


def esc(text):
    return html.escape(str(text or ''), quote=False)


def attr(text):
    return html.escape(str(text or ''), quote=True)


def has_any(text, terms):
    text = norm(text)
    return any(norm(t) in text for t in terms)


def cyrillic_ratio(text):
    letters = re.findall(r'[A-Za-zА-Яа-яЁё]', text or '')
    if not letters:
        return 0.0
    cyr = re.findall(r'[А-Яа-яЁё]', text or '')
    return len(cyr) / max(1, len(letters))


def blob(item):
    return ' '.join(str(item.get(k) or '') for k in ['title_ru', 'title_original', 'post_text', 'edited_post_text', 'source_text', 'url', 'source']).lower()


def text_blob(item):
    return norm(' '.join(str(item.get(k) or '') for k in ['title_ru', 'title_original', 'source_text', 'body', 'url', 'source']))


def fail(item, reason):
    item['status'] = 'rejected'
    item['reviewed_at'] = now_utc()
    item['reviewed_by'] = 'final-guard'
    item.setdefault('editor_notes', []).append(reason)
    if any(x in blob(item) for x in BAD_TEXT_MARKERS + BAD_URL_MARKERS):
        item['image_decision'] = 'drop'


def infer_category(item):
    text = text_blob(item)
    if has_any(text, INCIDENT_TERMS) and not has_any(text, MILITARY_TERMS):
        return '🇷🇺 РФ / происшествия'
    if has_any(text, MILITARY_TERMS):
        return '🇷🇺 РФ / война и безопасность'
    if has_any(text, GEOPOLITICS_TERMS):
        return '🧭 Геополитика'
    if has_any(text, ECON_TERMS):
        return '🇷🇺 РФ / экономика'
    if has_any(text, IT_TERMS):
        return '🌐 Мировые IT'
    if has_any(text, POLITICS_TERMS):
        return '🇷🇺 РФ / законы и политика'
    return item.get('category') or item.get('category_hint') or '🧭 Геополитика'


def strip_duplicate_halves(text):
    words = clean(text).split()
    if len(words) < 14:
        return clean(text)
    for n in range(min(40, len(words) // 2), 6, -1):
        a = ' '.join(words[:n]).lower()
        b = ' '.join(words[n:2*n]).lower()
        if a == b:
            return clean(' '.join(words[:n] + words[2*n:]))
    return clean(text)


def sentence_split(text):
    text = clean(text)
    parts = re.split(r'(?<=[.!?])\s+', text)
    out, seen = [], set()
    for part in parts:
        part = strip_duplicate_halves(part)
        if len(part) < 45:
            continue
        low = norm(part)
        if any(x in low for x in ['читать далее', 'continue reading', 'sign in', 'support us', 'подпис', 'реклама']):
            continue
        if len(part) > 250 and not re.search(r'[.!?]$', part):
            continue
        key = re.sub(r'\W+', '', low)[:140]
        if key in seen:
            continue
        seen.add(key)
        out.append(part)
        if len(out) >= 2:
            break
    return out


def text_has_duplicate_paragraphs(text):
    pars = [re.sub(r'\W+', '', p.lower())[:140] for p in re.split(r'\n\s*\n', text or '') if len(p.strip()) > 20]
    return len(pars) != len(set(pars))


def text_has_broken_tail(text):
    pars = [p.strip() for p in re.split(r'\n\s*\n', text or '') if p.strip()]
    if not pars:
        return True
    body = [p for p in pars if ' · <a href=' not in p and not p.startswith('<b>') and not p.startswith('🇷🇺') and not p.startswith('🌐') and not p.startswith('🧭')]
    for p in body:
        if len(p) > 120 and not re.search(r'[.!?…]$', re.sub(r'<[^>]+>', '', p).strip()):
            return True
    return False


def build_post(item, category):
    title = clean(item.get('title_ru') or item.get('title_original') or '')
    body = sentence_split(item.get('source_text') or '')
    if not body:
        body = [strip_duplicate_halves(clean(x)) for x in (item.get('body') or []) if clean(x)][:2]
    if not title or not body:
        return None
    footer = FOOTERS.get(category, category)
    return f"{esc(category)}\n\n<b>{esc(title)}</b>\n\n" + '\n\n'.join(esc(x) for x in body[:2]) + f"\n\n{esc(footer)} · <a href=\"{attr(item.get('url') or '')}\">{esc(item.get('source') or 'Источник')}</a>"


def should_polish(item, category, text):
    if item.get('category') != category:
        return True
    if text_has_duplicate_paragraphs(text):
        return True
    if text_has_broken_tail(text):
        return True
    if 'сообщает в пятницу пресс-служба' in norm(text) and norm(text).count('сообщает в пятницу пресс-служба') > 1:
        return True
    return False


def main():
    q = load_queue()
    changed = 0
    polished = 0
    for item in q.get('items', []) or []:
        if item.get('status') != 'approved':
            continue
        text = item.get('edited_post_text') or item.get('post_text') or ''
        b = blob(item)
        if any(x in b for x in BAD_URL_MARKERS + BAD_TEXT_MARKERS):
            fail(item, 'Финальный стоп: рекламный/товарный/служебный материал, не новость.')
            changed += 1
            continue
        category = infer_category(item)
        if should_polish(item, category, text):
            new_text = build_post(item, category)
            if new_text:
                item['category'] = category
                item['post_text'] = new_text
                item['edited_post_text'] = new_text
                item.setdefault('editor_notes', []).append('Final guard: категория и текст очищены перед публикацией; убраны повторы/битые фразы.')
                polished += 1
                text = new_text
            else:
                fail(item, 'Финальный стоп: не удалось собрать чистый текст без дублей и обрывов.')
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
    q['final_guard'] = {'changed': changed, 'polished': polished, 'checked_at': now_utc(), 'checked_at_sakhalin': now_sakh()}
    save_queue(q)
    print(f'final-guard: changed={changed}, polished={polished}')


if __name__ == '__main__':
    main()
