import os, re, json, html, time, hashlib, urllib.parse
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests
import feedparser

STATE = 'state.json'
TZ = timezone(timedelta(hours=11))
MAX_AGE_HOURS = 36
POSTS = 2
MODEL = os.getenv('OPENROUTER_MODEL') or 'openrouter/free'
OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'

FOOTER = {
    '📍 Сахалин': 'ЧП | САХАЛИН',
    '🌍 Мир о России': 'МИР О РОССИИ',
    '🇷🇺 Россия': 'РОССИЯ',
    '🧭 Геополитика': 'МИР | ГЕОПОЛИТИКА',
    '💻 IT / технологии': 'IT | ТЕХНОЛОГИИ',
}
BAD = ['подробности уточняются', 'по мере появления', 'событие относится', 'важно для жителей', 'система отметила']
SAKH = 'сахалин южно-сахалинск холмск корсаков курил курильск'.split()
RU = 'russia russian россия рф украина ukraine nato нато sanction sanctions санкции нефть oil gas газ g7'.split()
GEO = 'usa сша china китай iran иран israel израиль taiwan тайвань g7 nato нато война war конфликт conflict нефть oil газ gas'.split()
IT = 'openai ai ии нейросет google microsoft apple meta nvidia chip чип кибератака cyberattack утечка telegram android ios'.split()

def log(s):
    print(f'[{datetime.now(TZ):%Y-%m-%d %H:%M:%S} SAKH] {s}', flush=True)

def clean(x):
    s = html.unescape(str(x or ''))
    s = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', ' ', s, flags=re.I | re.S)
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

def esc(x): return html.escape(str(x or ''), quote=False)
def attr(x): return html.escape(str(x or ''), quote=True)
def norm(x): return re.sub(r'[^0-9a-zа-яё]+', ' ', clean(x).lower()).strip()
def title_hash(x): return hashlib.sha1(norm(x).encode()).hexdigest()

def similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b: return False
    if a == b or a in b or b in a: return True
    sa, sb = set(a.split()), set(b.split())
    return len(sa) >= 4 and len(sb) >= 4 and len(sa & sb) / max(1, min(len(sa), len(sb))) > 0.75

def has(text, words):
    t = ' ' + text.lower() + ' '
    return [w for w in words if w in t]

def gnews(q, lang='en', country='US'):
    return f'https://news.google.com/rss/search?q={urllib.parse.quote_plus(q)}&hl={lang}&gl={country}&ceid={country}:{lang}'

SOURCES = [
    ('Sakhalin', 'sakhalin', gnews('Сахалин OR Южно-Сахалинск OR Холмск OR Корсаков OR Курилы ДТП OR пожар OR происшествие OR землетрясение OR шторм OR авария OR розыск', 'ru', 'RU')),
    ('Interfax', 'ru', 'https://www.interfax.ru/rss.asp'),
    ('Reuters', 'world', gnews('site:reuters.com Russia Ukraine sanctions NATO China G7 oil gas')),
    ('AP News', 'world', gnews('site:apnews.com Russia Ukraine sanctions NATO China G7 oil gas Iran Israel')),
    ('BBC World', 'world', 'https://feeds.bbci.co.uk/news/world/rss.xml'),
    ('Guardian World', 'world', 'https://www.theguardian.com/world/rss'),
    ('BBC Technology', 'it', 'https://feeds.bbci.co.uk/news/technology/rss.xml'),
    ('Guardian Technology', 'it', 'https://www.theguardian.com/technology/rss'),
    ('Habr', 'it', 'https://habr.com/ru/rss/articles/'),
]

def is_google(url):
    host = urllib.parse.urlparse(url or '').netloc.lower()
    return 'news.google.' in host or host in ('google.com', 'www.google.com')

def abs_url(u, base=''):
    if not u: return None
    u = html.unescape(str(u).strip())
    if u.startswith('//'): u = 'https:' + u
    if base and u.startswith('/'): u = urllib.parse.urljoin(base, u)
    return u if u.startswith(('http://', 'https://')) else None

def entry_time(e):
    for k in ('published_parsed', 'updated_parsed'):
        v = e.get(k)
        if v: return datetime(*v[:6], tzinfo=timezone.utc)
    for k in ('published', 'updated'):
        try:
            raw = e.get(k)
            if raw:
                dt = parsedate_to_datetime(str(raw))
                return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        except Exception:
            pass
    return None

def fresh(dt):
    if not dt: return True
    age = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    return timedelta(0) <= age <= timedelta(hours=MAX_AGE_HOURS)

def direct_url(e):
    base = clean(e.get('link', ''))
    urls = []
    for raw in (str(e.get('summary', '') or ''), str(e.get('description', '') or '')):
        urls += re.findall(r'href=["\']([^"\']+)["\']', raw, flags=re.I)
    for lnk in e.get('links', []) or []:
        if isinstance(lnk, dict) and lnk.get('href'): urls.append(str(lnk['href']))
    for u in urls:
        u = abs_url(u, base)
        if u and not is_google(u): return u
    return abs_url(base) or base

def meta(page, key):
    pats = [
        rf'<meta[^>]+property=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(key)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(key)}["\']',
    ]
    for p in pats:
        m = re.search(p, page, re.I)
        if m: return html.unescape(m.group(1).strip())
    return None

def iso_dt(s):
    if not s: return None
    try:
        dt = datetime.fromisoformat(s.strip().replace('Z', '+00:00'))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except Exception:
        return None

def page_info(url):
    if not url or is_google(url): return {}
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 SkySakhNewsBot/1.0'}, timeout=30, allow_redirects=True)
        if r.status_code >= 400: return {}
        page = r.text[:700000]
        title_m = re.search(r'<title[^>]*>(.*?)</title>', page, re.I | re.S)
        img = meta(page, 'og:image') or meta(page, 'twitter:image')
        paragraphs = []
        for p in re.findall(r'<p[^>]*>(.*?)</p>', page, re.I | re.S):
            t = clean(p)
            if len(t) > 45 and not any(x in t.lower() for x in ('cookie', 'javascript', 'подпис', 'реклама')):
                paragraphs.append(t)
            if len(paragraphs) >= 4: break
        return {
            'url': r.url or url,
            'title': clean(meta(page, 'og:title') or meta(page, 'twitter:title') or (title_m.group(1) if title_m else '')),
            'desc': clean(meta(page, 'og:description') or meta(page, 'description') or meta(page, 'twitter:description')),
            'img': abs_url(img, r.url or url) if img else None,
            'published': iso_dt(meta(page, 'article:published_time') or meta(page, 'datePublished')),
            'text': ' '.join(paragraphs)[:1500],
        }
    except Exception as ex:
        log('page read failed: ' + str(ex)); return {}

def rss_img(e, raw, link):
    for k in ('media_thumbnail', 'media_content'):
        for m in e.get(k, []) or []:
            if isinstance(m, dict) and m.get('url'):
                u = abs_url(str(m['url']), link)
                if u: return u
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw or '', re.I)
    return abs_url(m.group(1), link) if m else None

def source_name(e, fallback):
    src = e.get('source')
    if isinstance(src, dict) and src.get('title'): return clean(src['title'])
    try:
        if getattr(src, 'title', None): return clean(src.title)
    except Exception:
        pass
    return fallback

def category(src_type, title, text, url):
    full = (title + ' ' + text).lower()
    path = urllib.parse.urlparse(url).path.lower()
    if src_type == 'sakhalin' or has(full, SAKH): return '📍 Сахалин', 100
    if src_type == 'it': return ('💻 IT / технологии', 70) if has(full, IT) else (None, 0)
    if src_type == 'world':
        if has(full, RU): return '🌍 Мир о России', 90
        if has(full, GEO): return '🧭 Геополитика', 72
    if '/russia/' in path: return '🇷🇺 Россия', 76
    return None, 0

def load_state():
    if not os.path.exists(STATE): return {'published_urls': [], 'published_title_hashes': [], 'last_posts': []}
    with open(STATE, 'r', encoding='utf-8') as f: s = json.load(f)
    s.setdefault('published_urls', []); s.setdefault('published_title_hashes', []); s.setdefault('last_posts', [])
    return s

def save_state(s):
    s['published_urls'] = s.get('published_urls', [])[-900:]
    s['published_title_hashes'] = s.get('published_title_hashes', [])[-900:]
    s['last_posts'] = s.get('last_posts', [])[-80:]
    s['last_run_sakhalin'] = datetime.now(TZ).isoformat(timespec='seconds')
    with open(STATE, 'w', encoding='utf-8') as f: json.dump(s, f, ensure_ascii=False, indent=2)

def collect(s):
    used_u, used_h = set(s.get('published_urls', [])), set(s.get('published_title_hashes', []))
    out = []
    for name, typ, url in SOURCES:
        log('Источник: ' + name)
        feed = feedparser.parse(url)
        for e in feed.entries[:14]:
            dt = entry_time(e)
            if not fresh(dt):
                log('old skip: ' + clean(e.get('title', ''))[:80]); continue
            raw = str(e.get('summary', '') or '')
            link = direct_url(e)
            if is_google(link):
                log('skip google wrapper: ' + clean(e.get('title', ''))[:80]); continue
            page = page_info(link)
            if page.get('published') and not fresh(page['published']):
                log('old meta skip: ' + clean(e.get('title', ''))[:80]); continue
            title = page.get('title') or clean(e.get('title', ''))
            text = ' '.join(x for x in (page.get('desc'), page.get('text'), clean(raw)) if x).strip()[:1800]
            link = page.get('url') or link
            th = title_hash(title)
            if link in used_u or th in used_h: continue
            cat, score = category(typ, title, text, link)
            if not cat: continue
            out.append({'id': len(out)+1, 'source': source_name(e, name), 'category_hint': cat, 'source_type': typ, 'score': score, 'title': title, 'summary': text, 'url': link, 'image_url': rss_img(e, raw, link) or page.get('img'), 'published_at': (page.get('published') or dt or datetime.now(timezone.utc)).isoformat(), 'title_hash': th})
    out.sort(key=lambda x: (x['category_hint'] != '📍 Сахалин', -x['score']))
    return out[:30]

def is_local(c): return c.get('category_hint') == '📍 Сахалин'

def prompt(cands):
    data = [{'id': c['id'], 'category': c['category_hint'], 'source': c['source'], 'title': c['title'], 'source_text': c['summary'], 'published_at': c['published_at']} for c in cands]
    return 'Ты редактор Telegram-канала SkySakhNews. Выбери ровно 2 свежие новости: одну сахалинскую, если есть, вторую из другого направления. Пиши как обычный новостной Telegram-канал: русский заголовок и 2-4 абзаца. Без списков, без слов Суть/Источник. Используй только факты из title/source_text, ничего не выдумывай. Верни только JSON: [{"id":1,"category":"📍 Сахалин","title_ru":"...","body":["абзац","абзац"],"footer":"ЧП | САХАЛИН"}]\nКандидаты:\n' + json.dumps(data, ensure_ascii=False)

def ask_ai(cands):
    key = os.getenv('OPENROUTER_API_KEY', '').strip()
    if not key: raise RuntimeError('OPENROUTER_API_KEY is missing')
    payload = {'model': MODEL, 'messages': [{'role':'system','content':'Возвращай только валидный JSON.'}, {'role':'user','content': prompt(cands)}], 'temperature': 0.07, 'max_tokens': 1600}
    r = requests.post(OPENROUTER_URL, headers={'Authorization':'Bearer '+key, 'Content-Type':'application/json', 'HTTP-Referer':'https://t.me/SkySakhNews', 'X-OpenRouter-Title':'SkySakhNews'}, json=payload, timeout=90)
    if r.status_code >= 400: raise RuntimeError(r.text[:500])
    t = r.json()['choices'][0]['message']['content'].strip()
    try: return json.loads(t)
    except Exception: return json.loads(t[t.find('['):t.rfind(']')+1])

def sentences(text): return [p.strip(' —-•') for p in re.split(r'(?<=[.!?])\s+|[;]\s+', clean(text)) if len(p.strip()) > 25]
def fallback_body(c):
    title = clean(c.get('title')); out = []
    for x in sentences(c.get('summary', '')):
        if any(b in x.lower() for b in BAD) or similar(x, title): continue
        out.append(x)
        if len(out) >= 3: break
    return out or [title]

def ru_title(t):
    t = clean(t); letters = re.findall(r'[A-Za-zА-Яа-яЁё]', t)
    latin = len([x for x in letters if re.match(r'[A-Za-z]', x)]) / len(letters) if letters else 0
    return t if latin < .35 else 'Мировые СМИ сообщили о новом развитии вокруг России'

def fallback_select(cands):
    loc, oth = [c for c in cands if is_local(c)], [c for c in cands if not is_local(c)]
    chosen = (loc[:1] + oth[:1]) or cands[:2]
    return [{'id': c['id'], 'category': c['category_hint'], 'title_ru': ru_title(c['title']), 'body': fallback_body(c), 'footer': FOOTER.get(c['category_hint'], 'НОВОСТИ')} for c in chosen[:2]]

def balance(items, cands):
    by = {c['id']: c for c in cands}; out = []
    for it in items:
        try: i = int(it.get('id'))
        except Exception: continue
        if i in by and i not in [x.get('id') for x in out]: out.append(it)
        if len(out) >= 2: break
    loc, oth = [c for c in cands if is_local(c)], [c for c in cands if not is_local(c)]
    ids = [int(x.get('id')) for x in out if str(x.get('id','')).isdigit()]
    if loc and not any(i in by and is_local(by[i]) for i in ids): out = [fallback_select(loc)[0]] + out[:1]
    ids = [int(x.get('id')) for x in out if str(x.get('id','')).isdigit()]
    if oth and not any(i in by and not is_local(by[i]) for i in ids): out = out[:1] + [fallback_select(oth)[0]]
    return (out or fallback_select(cands))[:2]

def body_lines(value, c):
    raw = [clean(x) for x in value if clean(x)] if isinstance(value, list) else sentences(str(value or ''))
    title = clean(c.get('title')); out = []
    for x in raw:
        if any(b in x.lower() for b in BAD) or similar(x, title): continue
        out.append(x)
        if len(out) >= 4: break
    return out or fallback_body(c)

def make_post(it, c, max_len):
    cat = clean(it.get('category') or c['category_hint']); title = ru_title(it.get('title_ru') or c['title']); lines = body_lines(it.get('body') or c.get('summary') or '', c)
    footer = clean(it.get('footer') or FOOTER.get(cat, 'НОВОСТИ')); source = clean(c.get('source') or 'Источник'); url = c['url']; u = attr(url)
    text = f'{esc(cat)}\n\n<b>{esc(title)}</b>\n\n' + '\n\n'.join(esc(x) for x in lines) + f'\n\n{esc(footer)} · <a href="{u}">{esc(source)}</a>\n<a href="{u}">&#8205;</a>'
    return text[:max_len], url

def tg(method, payload):
    token = os.getenv('TELEGRAM_BOT_TOKEN','').strip(); chat = os.getenv('TELEGRAM_CHANNEL_ID','').strip()
    if not token or not chat: raise RuntimeError('Telegram secrets missing')
    payload['chat_id'] = chat
    r = requests.post(f'https://api.telegram.org/bot{token}/{method}', data=payload, timeout=75)
    if r.status_code >= 400: raise RuntimeError(r.text[:700])
    return r.json()

def publish(it, c):
    if c.get('image_url'):
        cap, _ = make_post(it, c, 980)
        try:
            log('photo: ' + c['image_url'][:90])
            return tg('sendPhoto', {'photo': c['image_url'], 'caption': cap, 'parse_mode':'HTML'})
        except Exception as ex:
            log('photo failed: ' + str(ex))
    text, preview = make_post(it, c, 3000)
    return tg('sendMessage', {'text': text, 'parse_mode':'HTML', 'disable_web_page_preview': False, 'link_preview_options': json.dumps({'is_disabled': False, 'url': preview, 'prefer_large_media': True, 'show_above_text': False}, ensure_ascii=False)})

def main():
    state = load_state(); log('Сбор кандидатов')
    cands = collect(state); log(f'Кандидатов после фильтра свежести: {len(cands)}')
    if not cands: save_state(state); return
    try: selected = balance(ask_ai(cands), cands)
    except Exception as ex: log('AI fallback: ' + str(ex)); selected = fallback_select(cands)
    by = {c['id']: c for c in cands}; n = 0
    for it in selected[:POSTS]:
        try: c = by[int(it.get('id'))]
        except Exception: continue
        if c['url'] in state.get('published_urls', []): continue
        res = publish(it, c)
        if res.get('ok'):
            state.setdefault('published_urls', []).append(c['url']); state.setdefault('published_title_hashes', []).append(c['title_hash'])
            state.setdefault('last_posts', []).append({'time_sakhalin': datetime.now(TZ).isoformat(timespec='seconds'), 'source': c['source'], 'category': it.get('category') or c['category_hint'], 'title': it.get('title_ru') or c['title'], 'url': c['url'], 'with_image': bool(c.get('image_url')), 'published_at': c.get('published_at')})
            n += 1; time.sleep(12)
    log(f'Опубликовано: {n}'); save_state(state)

if __name__ == '__main__': main()
