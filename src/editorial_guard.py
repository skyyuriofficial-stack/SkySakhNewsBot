import difflib
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
PROPAGANDA_PHRASES = [
    'беззащитным детям', 'каратели', 'нацисты', 'террористический режим', 'прицельно ударили по спящим'
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
    return norm(' '.join(str(item.get(k) or '') for k in ['title_ru', 'title_original', 'source_text', 'body', 'url', 'source', 'post_text', 'edited_post_text']))


def fail(item, reason, status='rejected'):
    item['status'] = status
    item['reviewed_at'] = now_utc()
    item['reviewed_by'] = 'final-guard-v2'
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


def strip_duplicate_halves(text):
    words = clean(text).split()
    if len(words) < 14:
        return clean(text)
    for n in range(min(48, len(words) // 2), 6, -1):
        a = ' '.join(words[:n]).lower()
        b = ' '.join(words[n:2*n]).lower()
        if a == b:
            return clean(' '.join(words[:n] + words[2*n:]))
    return clean(text)


def sim_norm(text):
    text = clean(text).lower().replace('ё', 'е')
    text = re.sub(r'"[^"\n]{0,260}"', ' ', text)
    text = re.sub(r'\b(сообщил[аи]?|заявил[аи]?|написал[аи]?|уточнил[аи]?|добавил[аи]?|по данным|по словам|в оперштабе|в региональном оперштабе|губернатор[^.]{0,80})\b', ' ', text)
    text = re.sub(r'[^a-zа-я0-9 ]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def too_similar(a, b):
    aa, bb = sim_norm(a), sim_norm(b)
    if not aa or not bb:
        return False
    ratio = difflib.SequenceMatcher(None, aa, bb).ratio()
    wa, wb = set(aa.split()), set(bb.split())
    jaccard = len(wa & wb) / max(1, len(wa | wb))
    return ratio >= 0.74 or jaccard >= 0.62


def unique_texts(texts, limit=2):
    out = []
    for raw in texts:
        s = strip_duplicate_halves(clean(raw))
        if len(s) < 35:
            continue
        low = norm(s)
        if any(x in low for x in ['читать далее', 'continue reading', 'sign in', 'support us', 'подпис', 'реклама']):
            continue
        if has_any(low, PROPAGANDA_PHRASES):
            continue
        if any(too_similar(s, old) for old in out):
            continue
        out.append(s[:360])
        if len(out) >= limit:
            break
    return out


def sentence_split(text):
    text = clean(text)
    parts = re.split(r'(?<=[.!?])\s+', text)
    good = []
    for part in parts:
        part = strip_duplicate_halves(part)
        if len(part) < 45:
            continue
        if len(part) > 260 and not re.search(r'[.!?…]$', part):
            continue
        good.append(part)
    return unique_texts(good, limit=2)


def post_body_paragraphs(text):
    pars = [clean(re.sub(r'<[^>]+>', ' ', p)) for p in re.split(r'\n\s*\n', text or '') if clean(p)]
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
        if len(p) > 120 and not re.search(r'[.!?…]$', re.sub(r'<[^>]+>', '', p).strip()):
            return True
    return False


def is_pure_bpla_without_impact(item):
    text = text_blob(item)
    if not has_any(text, ['бпла', 'беспилотник', 'беспилотники', 'дрон', 'дроны']):
        return False
    if not has_any(text, PURE_BPLA_TERMS):
        return False
    return not has_any(text, REAL_IMPACT_TERMS)


def build_post(item, category):
    title = clean(item.get('title_ru') or item.get('title_original') or '')
    candidates = []
    candidates.extend(sentence_split(item.get('source_text') or ''))
    candidates.extend([clean(x) for x in (item.get('body') or []) if clean(x)])
    body = unique_texts(candidates, limit=2)
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
    if has_any(text, PROPAGANDA_PHRASES):
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
        if category == '🇷🇺 РФ / война и безопасность' and is_pure_bpla_without_impact(item):
            fail(item, 'Финальный стоп: рутинное сообщение о сбитых/уничтоженных БПЛА без жертв, ущерба или значимых последствий.')
            changed += 1
            continue
        if should_polish(item, category, text):
            new_text = build_post(item, category)
            if new_text and not text_has_duplicate_paragraphs(new_text) and not text_has_broken_tail(new_text):
                item['category'] = category
                item['post_text'] = new_text
                item['edited_post_text'] = new_text
                item.setdefault('editor_notes', []).append('Final guard v2: категория и текст очищены; удалены смысловые дубли/битые фразы.')
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
            fail(item, 'Финальный стоп: игровые новости публикуются только после ручного высокого приоритета; источник низкого приоритета.')
            changed += 1
            continue
    q['final_guard'] = {'version': 2, 'changed': changed, 'polished': polished, 'checked_at': now_utc(), 'checked_at_sakhalin': now_sakh()}
    save_queue(q)
    print(f'final-guard-v2: changed={changed}, polished={polished}')


if __name__ == '__main__':
    main()
