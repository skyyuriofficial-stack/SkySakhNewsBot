"""One-shot branch-only refinement. Abort on source drift; test before commit."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]

def replace(path, old, new):
    p = ROOT / path
    s = p.read_text(encoding='utf-8')
    if new in s:
        return
    assert s.count(old) == 1, (path, 'unexpected source drift', old[:80])
    p.write_text(s.replace(old, new, 1), encoding='utf-8')


def main():
    path = 'src/editorial_policy.py'
    replace(path,
        r'r"\bсбер(?:банк\w*|страховани\w*|инвестици\w*|нпф\w*|университет\w*)?\b"',
        r'r"\bсбер(?:банк\w*|страховани\w*|инвестици\w*|нпф\w*|университет\w*|а|у|ом|е)?\b"')
    replace(path,
        '''def _is_sber_routine_promotion(title: str) -> bool:
    return bool(
        _SBER_BRAND_RE.search(title)
        and not has_any(title, _SBER_MATERIAL_BANK_EVENTS)
    )''',
        '''def _is_sber_routine_promotion(title: str) -> bool:
    if not _SBER_BRAND_RE.search(title):
        return False
    # Mentioning default/bankruptcy inside financial advice is not an event
    # affecting the bank itself; inflected brand names must obey the same rule.
    advice = bool(re.search(
        r"как.{0,60}(?:избеж|защит|подготов)|совет.{0,50}(?:дефолт|банкрот)|"
        r"признаки.{0,25}(?:дефолт|банкрот)", title, re.I
    ))
    return advice or not has_any(title, _SBER_MATERIAL_BANK_EVENTS)''')

    path = 'src/mobilization_depth.py'
    replace(path,
        '''    if draft.get("depth_version") == VERSION:
        return draft
''',
        '''    # A model-supplied version flag is never permission to skip checks.
''')
    replace(path,
        '''    if any(r.get("evidence_kind") == "historical_reference" for r in law):''',
        '''    if any(r.get("evidence_kind") == "historical_reference" for r in law) and "Текущая стадия отдельно не подтверждена" not in legal:''')
    replace(path,
        '''    if "bill_text" in roles:
        legal += ''',
        '''    if "bill_text" in roles and "Анализ: предмет проекта" not in legal:
        legal += ''')
    replace(path,
        '''    if rationale:
        legal += ''',
        '''    if rationale and "Цель по пояснительной записке:" not in legal:
        legal += ''')
    replace(path,
        '''        purpose = "В сообщении указано: " + "; ".join(purposes) + "."''',
        '''        purpose = "В тексте обсуждаются категории: " + "; ".join(purposes) + "."''')
    replace(path,
        '''        valid = bool(refs) and all(str(i).isdigit() and int(i) in by_id for i in refs)
        valid = valid and len(clean(b.get("reasoning"))) >= 60 if isinstance(b, dict) else False''',
        '''        valid = supported_basis(b, by_id, axis)''')
    replace(path,
        '''            if not b.get("source_ids") or len(clean(b.get("reasoning"))) < 60:
                issues.append("unsupported_axis_rating:" + axis)''',
        '''            if not supported_basis(b, by_id, axis):
                issues.append("unsupported_axis_rating:" + axis)''')
    helper = '''def supported_basis(basis, by_id, axis):
    if not isinstance(basis, dict) or len(clean(basis.get("reasoning"))) < 60:
        return False
    refs = basis.get("source_ids") or []
    excerpt = clean(basis.get("evidence_excerpt"))
    if not refs or len(excerpt) < 30:
        return False
    if any(not str(i).isdigit() or int(i) not in by_id for i in refs):
        return False
    # Statutory powers alone are not evidence of manpower shortages or actual
    # readiness. Require a dated, current observational source and exact text.
    now = datetime.now(timezone.utc)
    patterns = {
        "near_term": r"мобилизац|комплектован|кадров|повестк|mobiliz|manpower|recruit",
        "staffing": r"потер|набор|комплектован|кадров|loss|manpower|recruit",
        "infrastructure": r"военком|сборн.{0,20}пункт|повестк|разверт|развёрт|deployment|draft notice",
    }
    for raw in refs:
        row = by_id[int(raw)]
        if row.get("group") == "law" or row.get("evidence_kind") == "historical_reference":
            continue
        try:
            stamp = datetime.fromisoformat(str(row.get("published_utc") or "").replace("Z", "+00:00"))
            if stamp.tzinfo is None or not (-7200 <= (now-stamp).total_seconds() <= 8*86400):
                continue
        except (ValueError, TypeError):
            continue
        if excerpt in clean(row.get("summary")) and re.search(patterns[axis], excerpt, re.I):
            return True
    return False


'''
    p = ROOT / path
    text = p.read_text(encoding='utf-8')
    if 'def supported_basis(' not in text:
        text = text.replace('def enrich_draft(draft, evidence):', helper + 'def enrich_draft(draft, evidence):', 1)
        p.write_text(text, encoding='utf-8')
    replace(path,
        '''            "Для каждого уровня риска добавь assessment_basis: ключ оси, source_ids и reasoning с причинной связью и альтернативным объяснением. "''',
        '''            "Для каждого уровня риска добавь assessment_basis: ключ оси, source_ids, evidence_excerpt (точный фрагмент текущего сообщения) и reasoning с причинной связью и альтернативным объяснением. Исторический закон не доказывает оперативную готовность или кадровый дефицит. "''')

    path = 'src/mobilization_depth_selftest.py'
    extra = '''    def test_model_flag_cannot_bypass_risk_check(self):
        d = {'depth_version': q.VERSION, 'assessment': {'near_term': 'НИЗКИЙ — указа нет'}}
        out = q.enrich_draft(d, [])
        self.assertTrue(out['assessment']['near_term'].startswith('НЕДОСТАТОЧНО'))

    def test_old_law_does_not_prove_current_staffing(self):
        row = {'id': 1, 'group': 'law', 'summary': 'Закон о мобилизационной подготовке и комплектовании войск', 'published_utc': '2026-10-27T00:00:00+00:00'}
        basis = {'source_ids': [1], 'reasoning': 'Подробное объяснение с причинной связью, которое однако не подкреплено текущим кадровым наблюдением.', 'evidence_excerpt': row['summary']}
        self.assertFalse(q.supported_basis(basis, {1: row}, 'staffing'))

    def test_sber_inflections_and_real_exceptions(self):
        import editorial_policy as policy
        for title in ('В Сбере рассказали, как копить на отпуск', 'Клиенты Сбера рассказали о накоплениях', 'Сбер рассказал, как избежать банкротства'):
            self.assertTrue(policy._is_sber_routine_promotion(title), title)
        for title in ('Сбер объявил дефолт по обязательствам', 'У Сбера произошёл масштабный сбой платежей'):
            self.assertFalse(policy._is_sber_routine_promotion(title), title)
        self.assertTrue(policy._is_foreign_vehicle_recall('Toyota объявила отзыв 228 тысяч минивэнов в США — в чем проблема'))

'''
    p = ROOT/path
    text = p.read_text(encoding='utf-8')
    if 'def test_model_flag_cannot_bypass_risk_check' not in text:
        text = text.replace('    def test_production_fallback_integration(self):', extra + '    def test_production_fallback_integration(self):', 1)
        p.write_text(text, encoding='utf-8')
    for f in ('src/editorial_policy.py', 'src/mobilization_depth.py', 'src/mobilization_depth_selftest.py'):
        ast.parse((ROOT/f).read_text(encoding='utf-8'))
    print('Finite source refinements applied; tests are required before commit.')

if __name__ == '__main__':
    main()
