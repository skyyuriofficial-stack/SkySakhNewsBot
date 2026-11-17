"""Offline regressions for durable foreign-source evidence and repeat audits."""

from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import publication_auditor as auditor
import publisher


# Synthetic source: the feed headline deliberately does not occur in the page
# excerpt, reproducing the BBC record's storage shape without a live fetch.
SOURCE_TITLE = "Russian drone hits security building in Kyiv, Zelensky says"
FINAL_TITLE = "Российский дрон ударил по зданию в Киеве, заявил Зеленский"
MISSING = "foreign_translation_evidence_missing"


def foreign_post():
    return {
        "title": FINAL_TITLE,
        "title_original": None,
        "source_text_excerpt": (
            "A Russian drone hit a building in the Ukrainian capital, the president said. "
            "Officials said the building was damaged."
        ),
        "source": "BBC World",
        "url": "https://www.bbc.com/news/test-durable-translation",
        "category_key": "world_ru",
        "category": "🌍 Мир о России",
        "footer": "МИР О РОССИИ",
        "news_director": {"title_original": SOURCE_TITLE},
        "publisher_version": "stable-v12.1",
        "time_sakhalin": datetime.now(timezone.utc).isoformat(),
        "telegram_message_id": 123,
        "telegram_chat_id": "test-chat",
        "publication_contract": {"approved": True, "foreign_evidence_ok": True},
        "grounded_evidence": True,
        "published_row": {
            "title_ru": FINAL_TITLE,
            "title_evidence": SOURCE_TITLE,
            "body": [
                "Президент Украины заявил, что российский беспилотник ударил по зданию в Киеве.",
                "По словам официальных лиц, здание было повреждено.",
            ],
            "body_evidence": [
                "A Russian drone hit a building in the Ukrainian capital, the president said",
                "Officials said the building was damaged",
            ],
            # Draft metadata is not an independent source-title fallback.
            "news_director": {"title_original": SOURCE_TITLE},
        },
    }


class TranslationAuditTests(unittest.TestCase):
    def setUp(self):
        network_patch = patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("regression attempted network access"),
        )
        self.network = network_patch.start()
        self.addCleanup(network_patch.stop)
        telegram_patch = patch.object(auditor, "_telegram_call")
        self.telegram = telegram_patch.start()
        self.addCleanup(telegram_patch.stop)
        self.telegram.return_value = {"ok": True}

    def audit(self, post, *, mutate=False):
        return auditor.audit_recent_posts(
            {"last_posts": [post]},
            category_map=publisher.core.b.CAT,
            render_caption=publisher.core.b.caption,
            mutate=mutate,
        )

    def assert_unresolved(self, post, *, mutate=False):
        report = self.audit(post, mutate=mutate)
        self.assertEqual((report["passed"], report["unresolved"]), (0, 1), report)
        self.assertIn(MISSING, post["post_audit"]["issues"])
        self.assertEqual(report["corrected"] + report["deleted"] + report["failed_actions"], [])
        self.telegram.assert_not_called()
        self.network.assert_not_called()

    def test_legacy_v12_recovers_independently_saved_source_title(self):
        post = foreign_post()
        post["time_sakhalin"] = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        before = copy.deepcopy(post)
        report = self.audit(post, mutate=True)
        self.assertEqual((report["checked"], report["passed"], report["unresolved"]), (1, 1, 0))
        self.assertIsNone(post["title_original"])
        self.assertEqual(post["published_row"], before["published_row"])
        self.telegram.assert_not_called()

    def test_explicit_source_title_works_without_review_metadata(self):
        post = foreign_post()
        post["title_original"] = SOURCE_TITLE
        post.pop("news_director")
        self.assertEqual(self.audit(post)["passed"], 1)

    def test_draft_evidence_and_approved_flags_cannot_supply_source_title(self):
        for metadata in (None, {}, "invalid metadata"):
            with self.subTest(metadata=metadata):
                post = foreign_post()
                post["news_director"] = metadata
                self.assert_unresolved(post)

    def test_explicit_conflicting_title_is_not_overridden_by_metadata(self):
        post = foreign_post()
        post["title_original"] = "An unrelated business announced a merger in another country"
        self.assert_unresolved(post)

    def test_missing_and_unmatched_evidence_remains_unresolved(self):
        for field, value in (
            ("title_evidence", ""),
            ("title_evidence", "An unrelated business announced a merger in another country"),
            ("body_evidence", []),
            ("body_evidence", ["Officials said the building was damaged"]),
            ("body_evidence", ["Unrelated evidence about another country"] * 2),
        ):
            with self.subTest(field=field, value=value):
                post = foreign_post()
                post["published_row"][field] = value
                self.assert_unresolved(post)

    def test_missing_excerpt_cannot_be_replaced_by_body_evidence(self):
        post = foreign_post()
        post["source_text_excerpt"] = ""
        self.assert_unresolved(post)

    def test_missing_draft_cannot_bypass_contract(self):
        post = foreign_post()
        post.pop("published_row")
        self.assert_unresolved(post)

    def test_missing_evidence_cannot_be_resolved_by_caption_edit(self):
        post = foreign_post()
        post["published_row"]["body_evidence"] = []
        self.assert_unresolved(post, mutate=True)

    def test_caption_edit_still_works_when_repaired_contract_passes(self):
        post = foreign_post()
        post["published_row"]["title_ru"] = SOURCE_TITLE
        report = self.audit(post, mutate=True)
        self.assertEqual((len(report["corrected"]), report["unresolved"]), (1, 0), report)
        self.assertEqual(self.telegram.call_args.args[0], "editMessageCaption")
        self.assertEqual(post["published_row"]["title_ru"], FINAL_TITLE)
        self.telegram.reset_mock()
        self.assertEqual(self.audit(post, mutate=True)["passed"], 1)
        self.telegram.assert_not_called()

    def test_historical_missing_evidence_stays_visible_without_mutation(self):
        post = foreign_post()
        post["time_sakhalin"] = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        post["published_row"]["body_evidence"] = []
        self.assert_unresolved(post, mutate=True)
        post["publisher_version"] = "legacy-v11"
        report = self.audit(post, mutate=True)
        self.assertEqual((report["passed"], len(report["anomalies"])), (0, 1))
        self.assertFalse(post["post_audit"]["approved"])
        self.telegram.assert_not_called()

    def test_repeat_audit_rechecks_evidence_instead_of_trusting_prior_approval(self):
        post = foreign_post()
        for _ in range(2):
            report = self.audit(post, mutate=True)
            self.assertEqual((report["passed"], report["unresolved"]), (1, 0))
        post["published_row"].pop("title_evidence")
        for _ in range(2):
            self.assert_unresolved(post, mutate=True)

    def test_collect_validate_save_and_reload_preserves_unchanged_source_title(self):
        post = foreign_post()
        candidate = auditor._candidate_from_post(post)
        candidate["title"] = SOURCE_TITLE
        candidate.pop("title_original")
        candidate["published_at"] = datetime.now(timezone.utc).isoformat()
        candidate["score"] = 100
        state = {"last_posts": [], "last_run": {"published": 0}}
        row = copy.deepcopy(post["published_row"])
        cache_names = (
            "_DIRECTOR_REPORT", "_DIRECTOR_BY_URL", "_CANDIDATE_BY_URL",
            "_ROW_BY_URL", "_CONTRACT_BY_URL", "_CAPTION_BY_URL",
        )
        with patch.multiple(publisher, **{key: {} for key in cache_names}), \
                patch.object(publisher, "_original_collect", return_value=[candidate]), \
                patch.object(publisher, "_original_valid_post", return_value=row), \
                patch.object(publisher, "_original_save_state") as save:
            selected = publisher.collect_with_news_director(state)
            self.assertEqual(len(selected), 1)
            self.assertFalse(selected[0].get("title_original"))
            validated = publisher.valid_post_with_news_director(selected[0])
            self.assertIsNotNone(validated)
            self.assertTrue(validated["publication_contract"]["foreign_evidence_ok"])
            state["last_posts"] = [copy.deepcopy(post)]
            state["last_run"]["published"] = 1
            publisher.save_state_with_news_director(state)
            saved = json.loads(json.dumps(save.call_args.args[0]))["last_posts"][0]
        self.assertEqual(saved["title_original"], SOURCE_TITLE)
        # New records remain independently auditable without the fallback.
        saved.pop("news_director")
        self.assertEqual(self.audit(saved, mutate=True)["passed"], 1)
        self.telegram.assert_not_called()
        self.network.assert_not_called()


def run_regressions():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TranslationAuditTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("translation publication-audit regressions failed")


if __name__ == "__main__":
    run_regressions()
