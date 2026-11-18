"""Offline regressions. Never sends Telegram or contacts an LLM."""
import unittest
from unittest.mock import patch
import mobilization_depth as q


class DepthTests(unittest.TestCase):
    def test_query_no_frozen_month(self):
        rows = q.dated_queries([('isw', 'Russia mobilization September 2026 when:4d', 'en', 'US'), ('law', '1322096-8 when:7d', 'ru', 'RU')])
        self.assertNotIn('September', rows[0][1])
        self.assertIn('when:4d', rows[0][1])
        self.assertEqual(rows[1][1], '1322096-8 when:7d')

    def test_civil_no_invented_purpose(self):
        out = q.direct_civil_claim({'title': 'Повестки запасникам', 'summary': 'Запасники сообщают о повестках в нескольких регионах.', 'published_utc': '2026-11-01T09:00:00+00:00'})
        self.assertNotIn('уточнение учётных', out)
        self.assertIn('не установлена', out)
        self.assertIn('2026-11-01', out)

    def test_civil_contract_not_records(self):
        out = q.direct_civil_claim({'title': 'Запасников вызывают', 'summary': 'Запасникам вручают повестки для заключения контракта.', 'published_utc': '2026-11-01T09:00:00+00:00'})
        self.assertIn('контрактная служба', out)
        self.assertNotIn('уточнение учётных', out)

    def test_quote_is_literal(self):
        body = 'Преамбула. Неисполнение решения губернатора, принятого в пределах его компетенции, влечет административный штраф. Следующее положение.'
        result = q.literal_quote(body, r'Неисполнение решения')
        self.assertIn(result, body)
        self.assertLessEqual(len(result.split()), 22)

    def test_current_snapshot_not_removed_by_baseline(self):
        a = {'url': 'https://sozd.duma.gov.ru/bill/1322096-8', 'group': 'law', 'title': 'Историческая дата', 'summary': '1322096-8 принят в первом чтении 27.10.2026', 'legal_role': 'first_reading_baseline', 'trust': 100}
        b = {**a, 'summary': '1322096-8 сведения из текущей карточки', 'legal_role': 'stage_snapshot', 'retrieved_text': '1322096-8 сведения из текущей карточки', 'evidence_kind': 'retrieved_legal_text'}
        result = q.merge_evidence([a], [b])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['legal_role'], 'stage_snapshot')
        self.assertEqual(result[1]['evidence_kind'], 'historical_reference')
        self.assertEqual(result[0]['event_family'], result[1]['event_family'])

    def test_bad_quote_rejected(self):
        issues = q.depth_issues({'legal_quotes': [{'source_id': 1, 'text': 'Объявлена мобилизация'}]}, [{'id': 1, 'retrieved_text': 'Такого решения нет'}])
        self.assertIn('quotation_not_in_retrieved_document', issues)

    def test_levels_require_support(self):
        d = {'assessment': {'near_term': 'НИЗКИЙ — указ не найден', 'staffing': 'УМЕРЕННОЕ', 'infrastructure': 'СРЕДНЯЯ'}}
        out = q.enrich_draft(d, [])
        self.assertTrue(out['assessment']['near_term'].startswith('НЕДОСТАТОЧНО'))
        self.assertEqual(q.depth_issues(out, []), [])

    def test_quote_only_fulltext(self):
        d = q.enrich_draft({'legal': 'Обзор', 'assessment': {}}, [{'id': 1, 'group': 'law', 'legal_role': 'bill_text', 'summary': 'Пересказ', 'literal_quote': 'Неисполнение решения'}])
        self.assertEqual(d['legal_quotes'], [])

    def test_html_escaped(self):
        d = {'headline': '<test>', 'short': 'Нет данных', 'legal': 'Норма <script>', 'practice': 'Ограничение', 'assessment': {}}
        out = q.format_message(d, [], 'morning')
        self.assertIn('&lt;test&gt;', out)
        self.assertNotIn('<script>', out)

    def test_visible_limit(self):
        self.assertEqual(q.visible_units('<b>abc</b>'), 3)
        self.assertEqual(q.visible_units('🇷🇺'), 4)

    def test_retrieval_does_not_invent_effective_date(self):
        class Resp:
            status_code = 200
            text = 'Неисполнение решения губернатора влечет административный штраф. ' * 20
        rows = q.fetch_legal_snapshots(lambda *a, **kw: Resp(), lambda t: t)
        for row in rows:
            self.assertIsNone(row['published_utc'])
            self.assertIs(row['current_stage_verified'], False)
            self.assertIn(row['literal_quote'], row['retrieved_text'])

    def test_model_flag_cannot_bypass_risk_check(self):
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

    def test_reader_first_digest_with_conditional_impacts(self):
        import mobilization_sources as sources
        import mobilization_digest_final as final
        import mobilization_digest as digest
        evidence = sources.verified_legal_reference_rows() + [{
            'group': 'civil_society',
            'trust': 84,
            'source': 'Идите лесом',
            'title': 'Запасникам: выезд, повестки и мобилизационное предписание',
            'summary': (
                'В проект обращаются запасники и родственники. Многие спрашивают '
                'про уточнение учётных данных, военные сборы, мобилизационные '
                'предписания, выезд из России и неявку в военкомат.'
            ),
            'url': 'https://t.me/iditelesom_help/8304',
            'published_utc': '2026-11-13T12:00:00+00:00',
        }]
        evidence = q.merge_evidence(evidence, [])
        draft = q.enrich_draft(final.safe_fallback_draft(evidence), evidence)
        text = q.format_message(draft, evidence, 'morning')
        for required in (
            '<b>Главное</b>',
            'Что может стать строже',
            'Что действует сейчас',
            'Что стало легче?',
            'Повестки: что происходит на практике',
            'Оценка риска',
            'Проверить первоисточники',
            '3–5 тыс.',
            '30–50 тыс.',
            '300 тыс.',
            '31-ФЗ',
            '757',
            '27.10.2026',
            'https://t.me/iditelesom_help/8304',
            'https://sozd.duma.gov.ru/bill/1322096-8',
        ):
            self.assertIn(required, text, required)
        self.assertIn('Если норму примут', text)
        self.assertIn('актуальный статус', text)
        self.assertNotIn('<b>Раздельная оценка</b>', text)
        self.assertNotIn('<b>Право: содержание и последствия</b>', text)
        self.assertNotIn('[10]', text)
        self.assertNotIn('Фрагмент нормы:', text)
        self.assertLessEqual(q.visible_units(text), 4000)
        self.assertLessEqual(len(text), 4000)
        self.assertEqual(final._rendered_digest_issues(text, evidence), [])
        self.assertEqual(final._reader_issues(text, evidence), [])
        draft["previous_civil_report"] = draft["rendered_civil_report"]
        repeated = q.format_message(draft, evidence, "evening")
        self.assertIn("уже разбирали в прошлом выпуске", repeated)
        self.assertNotIn("уже разбирали в прошлом выпуске", text)
        old_layout = text.replace("Что действует сейчас", "Право: содержание и последствия")
        self.assertTrue(final._reader_issues(old_layout, evidence))
        footnotes = text.replace("«Идите лесом» · сообщение", "[10]")
        self.assertIn("attributed_civil_report_missing", final._reader_issues(footnotes, evidence))

    def test_no_unverified_improvement_and_no_fabricated_stage(self):
        draft = {
            'headline': 'Сведения о повестках',
            'short': 'Сведения требуют проверки',
            'legal': 'Текст нормы только из непроверенного заголовка',
            'practice': 'Не хватает данных',
            'assessment': {'started': 'НЕ УСТАНОВЛЕН ПО ВЫБОРКЕ',
                           'near_term': 'НЕДОСТАТОЧНО ДАННЫХ'},
        }
        evidence = [{'id': 1, 'group': 'law', 'legal_role': 'stage_snapshot',
                     'summary': '1322096-8 — стадия требует проверки',
                     'url': 'https://example.org/1'}]
        self.assertIsNone(q._plain_language_legal(draft, evidence))
        text = q.format_message(draft, evidence, 'evening')
        self.assertIn('Текущую стадию документов', text)
        self.assertNotIn('27.10.2026', text)
        self.assertIn('недостаточно', text.lower())
        self.assertLessEqual(q.visible_units(text), 4000)

    def test_long_live_layout_preserves_law_and_attribution(self):
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
        self.assertIn(q.clean(draft['items'][0]['text']), out)
        self.assertIn('https://example.org/4', out)

    def test_quote_does_not_repeat_legal_heading(self):
        text = 'Неисполнение решения. Неисполнение решения губернатора, за исключением случаев, предусмотренных статьей 20.5.1 настоящего Кодекса, влечет штраф.'
        quote = q.source_quote(text, 'bill_text')
        self.assertEqual(quote, 'за исключением случаев, предусмотренных статьей 20.5.1 настоящего Кодекса')
        self.assertIn(quote, text)
        self.assertEqual(q.source_quote('Неполный заголовок нормы', 'bill_text'), '')
        self.assertEqual(q.source_quote('Президент объявляет общую или частичную мобилизацию с уведомлением палат.', 'presidential_powers'), 'объявляет общую или частичную мобилизацию')

    def test_production_fallback_integration(self):
        import mobilization_digest as digest
        import mobilization_digest_final as final
        import mobilization_digest_runner as runner
        import mobilization_sources as sources
        q.install(digest, final, sources, runner)
        rows = sources.verified_legal_reference_rows()
        rows += [{
            'source': 'Идите лесом', 'group': 'civil_society', 'trust': 84,
            'title': 'Повестки запасникам',
            'summary': 'Запасники сообщают о повестках для заключения контракта. Обращения поступили из нескольких регионов.',
            'url': 'https://t.me/iditelesom_help/999999',
            'published_utc': '2026-11-01T09:00:00+00:00',
        }]
        evidence = q.merge_evidence(rows, [])
        with patch('requests.post', side_effect=AssertionError('No network in self-test')):
            draft = final.safe_fallback_draft(evidence)
            issues = digest.validate_draft(draft, evidence)
            self.assertEqual(issues, [], issues)
            message = digest.format_message(draft, evidence, 'morning')
        self.assertIn('19.5.5', message)
        self.assertIn('31-ФЗ', message)
        self.assertIn('757', message)
        self.assertIn('контрактная служба', message)
        self.assertIn('https://t.me/iditelesom_help/999999', message)
        self.assertIn('НЕДОСТАТОЧНО ДАННЫХ', message)
        self.assertLessEqual(q.visible_units(message), 4000)
        self.assertEqual(q.enrich_draft(draft, evidence), draft)
        print('Production digest visible characters:', q.visible_units(message))
        print('--- VERIFIED OFFLINE PREVIEW ---\n' + message)


if __name__ == '__main__':
    unittest.main(verbosity=2)
