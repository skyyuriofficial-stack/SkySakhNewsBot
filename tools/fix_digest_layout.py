from pathlib import Path
import ast
ROOT = Path(__file__).resolve().parents[1]
p = ROOT/'src/mobilization_depth.py'
s = p.read_text(encoding='utf-8')
def change(old, new):
    global s
    if new in s:
        return
    assert s.count(old) == 1, old[:100]
    s = s.replace(old, new, 1)

helper = r'''def source_quote(text, role):
    """Short complete syntactic fragments, not the first N header words."""
    patterns = {
        "presidential_powers": r"объявляет общую или частичную мобилизацию",
        "bill_text": r"за исключением случаев, предусмотренных статьей 20\.5\.1 (?:настоящего Кодекса|КоАП)",
        "bill_rationale": r"в целях установления административной ответственности за неисполнение решений",
        "regional_framework": r"являются обязательными для исполнения гражданами, организациями",
    }
    match = re.search(patterns.get(role, r"(?!)"), clean(text), re.I)
    return match.group(0) if match else ""


'''
if 'def source_quote(' not in s:
    s = s.replace('def fetch_legal_snapshots(get, strip_html):', helper+'def fetch_legal_snapshots(get, strip_html):', 1)
change('quote = literal_quote(text, pattern)', 'quote = source_quote(text, role)')
change('text = body or title', 'text = re.sub(r"^З\\s+апасник", "Запасник", body or title)')
change('legal += " Цель по пояснительной записке: " + sentence_excerpt(rationale["summary"], 310)',
       'legal += " Цель по пояснительной записке: установить федеральную ответственность за неисполнение решений региональных властей и оперштабов в пределах их компетенции."')
change('for row in law:\n        quote = clean(row.get("literal_quote"))',
       'for row in sorted(law, key=lambda r: {"presidential_powers": 0, "bill_text": 1, "bill_rationale": 2}.get(r.get("legal_role"), 3)):\n        quote = clean(row.get("literal_quote"))')
change('parts.append("«" + esc(quote.get("text")) + "» " + refs([quote.get("source_id")]))',
       'parts.append("Фрагмент нормы: «" + esc(quote.get("text")) + "» " + refs([quote.get("source_id")]))')
change('esc(practice) + " " + refs(sections.get("practice", [])[:2])',
       'esc(practice) + " " + refs([i for _, values in stories[:story_count] for i in values if by_id.get(i, {}).get("group") == "civil_society"] or sections.get("practice", [])[:2])')
change('    legal = clean(draft.get("legal"))\n', r'''    legal = clean(draft.get("legal"))
    legal = legal.replace(
        "Предлагаемые, ещё НЕ действующие санкции:",
        "Санкции по проекту (вступление в силу отдельно не подтверждено):"
    )
    # Inline quotations inherited from a cached template are not live-document
    # quotations. Only the independently verified legal_quotes are rendered.
    legal = re.sub(
        r"Из текста проекта:\s*«[^»]+»\s*[—-]\s*это описание состава правонарушения, а не мобилизационный призыв\.",
        "Предлагаемый состав правонарушения не является решением о призыве.",
        legal,
    )
''')
ast.parse(s)
p.write_text(s, encoding='utf-8')

p=ROOT/'src/mobilization_depth_selftest.py'
s=p.read_text(encoding='utf-8')
extra='''    def test_quote_does_not_repeat_legal_heading(self):
        text = 'Неисполнение решения. Неисполнение решения губернатора, за исключением случаев, предусмотренных статьей 20.5.1 настоящего Кодекса, влечет штраф.'
        quote = q.source_quote(text, 'bill_text')
        self.assertEqual(quote, 'за исключением случаев, предусмотренных статьей 20.5.1 настоящего Кодекса')
        self.assertIn(quote, text)
        self.assertEqual(q.source_quote('Неполный заголовок нормы', 'bill_text'), '')
        self.assertEqual(q.source_quote('Президент объявляет общую или частичную мобилизацию с уведомлением палат.', 'presidential_powers'), 'объявляет общую или частичную мобилизацию')

'''
if 'def test_quote_does_not_repeat_legal_heading' not in s:
    s=s.replace('    def test_production_fallback_integration(self):',extra+'    def test_production_fallback_integration(self):',1)
ast.parse(s)
p.write_text(s,encoding='utf-8')
print('Meaningful literal excerpts only; malformed scraped fragments removed.')
