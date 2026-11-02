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
