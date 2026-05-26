import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

from editorial_text import build_post_text, cyrillic_ratio, too_similar, PROPAGANDA_PHRASES

QUEUE_FILE = Path('editorial_queue.json')
SAKH_TZ = timezone(timedelta(hours=11))

LOW_PRIORITY_GAME_SOURCES = {'GameSpot', 'IGN', 'Eurogamer', 'PC Gamer'}
BAD_URL_MARKERS = ['nvidia.com/en-us/drivers', 'amazon.', 'walmart.', 'woot.com']
BAD_TEXT_MARKERS = [
    'download the latest', 'official nvidia drivers', 'lowest price', 'free shipping', 'prime members',
    'less than $', 'under $', 'deal', 'sale', 'discount', 'coupon', 'power bank'
]

INCIDENT_TERMS = [
    'пожар', 'дтп', 'авария', 'аварии', 'утонул', 'утонули', 'погибли в результате пожара',
    'краж', 'мошеннич', 'убийств', 'нападение', 'обрушение', 'чп', 'происшеств',
    'лавина', 'спасатели', 'пропали', 'без воды', 'водопровод'
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
    'азербайджан', 'грузия', 'молдавия', 'молдова', 'постсоветск', 'трамп', 'авраам'
]
IT_TERMS = [
    'openai', 'chatgpt', 'google ai', 'gemini', 'microsoft ai', 'anthropic', 'claude', 'nvidia',
    'apple intelligence', 'искусственный интеллект', 'нейросет', 'llm', 'gpt', 'cve', 'уязвим',
    'кибер', 'cyber', 'data center', 'server', 'software', 'чип', 'процессор',
    'космос', 'шэньчжоу', 'тяньгун', 'орбит', 'тайконавт'
]

PURE_BPLA_TERMS = [
    'уничтожен', 'уничтожены', 'сбит', 'сбиты', 'сбито', 'перехвачен', 'перехвачены',
    'нейтрализован', 'нейтрализованы', 'ликвидации бпла', 'над территорией', 'над областью',
    'над регионом', 'за ночь уничтожены', 'за ночь сбиты'
]
REAL_IMPACT_TERMS = [
    'погиб', 'погибли', 'скончал', 'ранен', 'ранены', 'пострадал', 'пострадали', 'жертвы',
    'поврежден', 'повреждены', 'повреждена', 'разрушен', 'разрушены', 'пожар', 'возгорание',
    'ущерб', 'эвакуац', 'обесточ', 'без электричества', 'без света', 'отключени',
    'попадание', 'попал', 'прилет', 'прилёт', 'атаковал автомобиль', 'атаковали автомобиль'
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


def has_any(text, terms):
    text = norm(text)
    return any(norm(t) in text for t in terms)


def blob(item):
    return ' '.join(str(item.get(k) or '') for k in ['title_ru', 'title_original', 'post_text', 'edited_post_text', 'source_text', 'url', 'source']).lower()


def text_blob(item):
    return norm(' '.join(str(item.get(k) or '') for k in ['title_ru', 'title_original', 'source_text', 'body', 'url', 'source', 'post_text', 'edited_post_text']))


def fail(item, reason, status='rejected'):
    item['status'] = status
    item['reviewed_at'] = now_utc()
    item['reviewed_by'] = 'final-guard-v3'
    item.setdefault('editor_notes', []).append(reason)
    if any(x in blob(item) for x in BAD_TEXT_MARKERS + BAD_URL_MARKERS):
        item['image_decision'] = 'drop'


def infer_category(item):
    text = text_blob(item)
    if has_any(text, INCIDENT_TERMS) and not has_any(text, MILITARY_TERMS):
        return '🇷🇺 РФ / происшествия'
    if has_any(text, GEOPOLITICS_TERMS):
        return '🧭 Геополитика'
    if has_any(text, IT_TERMS):
        return '🌐 Мировые IT'
    if has_any(text, MILITARY_TERMS):
        return '🇷🇺 РФ / война и безопасность'
    if has_any(text, ECON_TERMS):
        return '🇷🇺 РФ / экономика'
    if has_any(text, POLITICS_TERMS):
        return '🇷🇺 РФ / законы и политика'
    return item.get('category') or item.get('category_hint') or '🧭 Геополитика'


def post_body_paragraphs(text):
    import html
    pars = [re.sub(r'<[^>]+>', ' ', html.unescape(p)).strip() for p in re.split(r'\n\s*\n', text or '') if p.strip()]
    out = []
    for p in pars:
        low = norm(p)
        if low.startswith(('🇷🇺', '🌍', '🧭', '🌐', '🎮', '📍')):
            continue
        if '·' in p and any(src in low for src in ['interfax', 'bbc', 'guardian', 'reuters', 'источник']):
            continue
        out.append(p)
    return out


def text_has_duplicate_paragraphs(text):
    pars = post_body_paragraphs(text)
    if len(pars) < 2:
        return False
    for i, a in enumerate(pars):
        for b in pars[i + 1:]:
            if too_similar(a, b):
                return True
    return False


def text_has_broken_tail(text):
    body = post_body_paragraphs(text)
    if not body:
        return True
    for p in body:
        stripped = re.sub(r'<[^>]+>', '', p).strip()
        if len(stripped) > 150 and not re.search(r'[.!?…]$', stripped):
            return True
    return False


def is_pure_bpla_without_impact(item):
    text = text_blob(item)
    if not has_any(text, ['бпла', 'беспилотник', 'беспилотники', 'дрон', 'дроны']):
        return False
    if not has_any(text, PURE_BPLA_TERMS):
        return False
    return not has_any(text, REAL_IMPACT_TERMS)


def build_clean_post(item, category):
    title, body, post = build_post_text(item, category)
    if not title or not body:
        return None
    if text_has_duplicate_paragraphs(post) or text_has_broken_tail(post):
        return None
    return title, body, post


def should_polish(item, category, text):
    if item.get('category') != category:
        return True
    if text_has_duplicate_paragraphs(text):
        return True
    if text_has_broken_tail(text):
        return True
    if has_any(text, PROPAGANDA_PHRASES):
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
        if category == '🇷🇺 РФ / война и безопасность' and is_pure_bpla_without_impact(item):
            fail(item, 'Финальный стоп: рутинное сообщение о сбитых/уничтоженных БПЛА без жертв, ущерба или значимых последствий.')
            changed += 1
            continue
        if should_polish(item, category, text):
            built = build_clean_post(item, category)
            if built:
                title, body, new_text = built
                item['category'] = category
                item['title_ru'] = title
                item['body'] = body
                item['post_text'] = new_text
                item['edited_post_text'] = new_text
                item.setdefault('editor_notes', []).append('Final guard v3: текст пересобран shared robust builder; дубли/битые фразы удалены.')
                polished += 1
                text = new_text
            else:
                fail(item, 'Финальный стоп: не удалось собрать чистый текст без смысловых дублей и обрывов.')
                changed += 1
                continue
        if cyrillic_ratio(text) < 0.45:
            fail(item, 'Финальный стоп: approved-пост не русифицирован, публикация запрещена.')
            changed += 1
            continue
        if item.get('category') == '🎮 Игры / индустрия' and item.get('source') in LOW_PRIORITY_GAME_SOURCES:
            fail(item, 'Финальный стоп: игровые новости публикуются только после высокого приоритета; источник низкого приоритета.')
            changed += 1
            continue
    q['final_guard'] = {'version': 3, 'changed': changed, 'polished': polished, 'checked_at': now_utc(), 'checked_at_sakhalin': now_sakh()}
    save_queue(q)
    print(f'final-guard-v3: changed={changed}, polished={polished}')


if __name__ == '__main__':
    main()
