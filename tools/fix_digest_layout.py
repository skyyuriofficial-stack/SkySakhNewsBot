from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / 'src/mobilization_depth.py'
s = p.read_text(encoding='utf-8')
start = s.index('def format_message(draft, evidence, mode):')
end = s.index('\n\ndef install(', start)
new = r'''def format_message(draft, evidence, mode):
    """Fit by dropping repetitive presentation, never by cutting legal clauses.

    The complete evidence/draft remains available in the digest state. The
    single Telegram overview keeps at least the first non-legal story, every
    legal clause, and links to any omitted secondary stories.
    """
    by_id = {int(r["id"]): r for r in evidence}
    def refs(values):
        links, seen = [], set()
        for value in values:
            try:
                idx = int(value)
            except (ValueError, TypeError):
                continue
            row = by_id.get(idx)
            url = str((row or {}).get("url") or "")
            if url in seen or urlsplit(url).scheme not in {"https", "http"}:
                continue
            seen.add(url)
            links.append(f'<a href="{html.escape(url, quote=True)}">[{idx}]</a>')
        return " ".join(links)
    esc = lambda v: html.escape(clean(v))
    sections = draft.get("section_sources") or {}
    label = "УТРЕННЯЯ" if mode == "morning" else "ВЕЧЕРНЯЯ"
    stories = []
    for item in (draft.get("items") or [])[:6]:
        item_ids = [int(i) for i in item.get("source_ids", []) if str(i).isdigit()]
        if item_ids and all(by_id.get(i, {}).get("group") == "law" for i in item_ids):
            continue
        stories.append((item, item_ids))
    labels = {"started": "Запуск", "near_term": "Ближайшие месяцы", "staffing": "Кадры", "infrastructure": "Готовность", "large_wave_decision": "Крупная волна"}

    def render(story_count, compact):
        parts = [f"🇷🇺 <b>МОБИЛИЗАЦИЯ РФ — {label} СВОДКА</b>", f"<b>{esc(draft.get('headline'))}</b>"]
        if not compact:
            parts.append(esc(draft.get("short")))
        for item, item_ids in stories[:story_count]:
            # Keep the full attributed summary, including its limitations.
            parts.append(esc(item.get("text")) + " " + refs(item_ids))
        rest = [idx for _, item_ids in stories[story_count:] for idx in item_ids]
        if rest:
            parts.append("Другие сообщения в выборке: " + refs(rest))
        parts += ["<b>Право: содержание и последствия</b>", esc(draft.get("legal")) + " " + refs(sections.get("legal", []))]
        for quote in (draft.get("legal_quotes") or [])[:2]:
            parts.append("«" + esc(quote.get("text")) + "» " + refs([quote.get("source_id")]))
        if compact and sections.get("practice"):
            practice = "«Идите лесом»: сообщения проекта, не независимое подтверждение массовости. Учёт, сборы, контракт и мобилизация различаются."
        else:
            practice = clean(draft.get("practice"))
        parts += ["<b>Практика и покрытие источников</b>", esc(practice) + " " + refs(sections.get("practice", [])[:2])]
        if sections.get("isw"):
            parts.append(esc(sentence_excerpt(draft.get("isw"), 300)) + " " + refs(sections["isw"][:2]))
        else:
            parts.append("Свежих данных ISW в выборке нет; это пробел покрытия, а не оценка риска.")
        parts.append("<b>Раздельная оценка</b>")
        for axis, axis_label in labels.items():
            parts.append(f"<b>{axis_label}:</b> {esc((draft.get('assessment') or {}).get(axis))}")
        return "\n\n".join(p for p in parts if p).strip()

    candidates = [(min(3, len(stories)), False), (min(2, len(stories)), True), (min(1, len(stories)), True)]
    for count, compact in candidates:
        message = render(count, compact)
        if visible_units(message) <= 4000:
            return message
    raise ValueError("digest cannot fit without losing a legal clause or primary attributed story")
'''
s = s[:start] + new + s[end:]
ast.parse(s)
p.write_text(s, encoding='utf-8')

p = ROOT / 'src/mobilization_depth_selftest.py'
s = p.read_text(encoding='utf-8')
extra = '''    def test_long_live_layout_preserves_law_and_attribution(self):
        legal = ('Полная юридическая норма: проект не равен действующему закону. ' * 20).strip()
        evidence = [{'id': i, 'url': f'https://example.org/{i}', 'group': 'civil_society'} for i in range(1, 5)]
        draft = {
            'headline': 'Проверка юридического статуса и региональной практики',
            'short': 'Повторяющийся вводный текст. ' * 12,
            'legal': legal,
            'items': [{'text': 'Сообщение проекта: ' + ('Региональный факт, требующий проверки. ' * 12), 'source_ids': [i]} for i in range(1, 5)],
            'practice': 'Оговорка об ограниченности наблюдений. ' * 10,
            'section_sources': {'legal': [], 'practice': [1, 2]},
            'assessment': {key: 'НЕДОСТАТОЧНО ДАННЫХ — вывод ограничен имеющимися свидетельствами.' for key in ('started', 'near_term', 'staffing', 'infrastructure', 'large_wave_decision')},
        }
        out = q.format_message(draft, evidence, 'morning')
        self.assertLessEqual(q.visible_units(out), 4000)
        self.assertIn(legal, out)
        self.assertIn(draft['items'][0]['text'], out)
        self.assertIn('https://example.org/4', out)

'''
if 'def test_long_live_layout_preserves_law_and_attribution' not in s:
    s = s.replace('    def test_production_fallback_integration(self):', extra + '    def test_production_fallback_integration(self):', 1)
ast.parse(s)
p.write_text(s, encoding='utf-8')
print('Layout fixed; legal content and the primary attributed report remain intact.')
