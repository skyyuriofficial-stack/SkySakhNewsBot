"""Read public sources and render the production fallback without sending it."""
from __future__ import annotations
import json
from pathlib import Path
import mobilization_digest as digest
import mobilization_digest_final as final
import mobilization_digest_runner as runner
import mobilization_sources as sources
import mobilization_depth as depth


def main():
    depth.install(digest, final, sources, runner)
    snapshots = depth.fetch_legal_snapshots(sources.requests.get, sources.clean)
    civil = sources.fetch_iditelesom_recent()
    evidence = depth.merge_evidence(sources.verified_legal_reference_rows() + civil, snapshots)
    draft = final.safe_fallback_draft(evidence)
    issues = digest.validate_draft(draft, evidence)
    if issues:
        raise AssertionError(issues)
    text = digest.format_message(draft, evidence, 'morning')
    report = {
        'mode': 'read_only_live_preview',
        'telegram_sent': False,
        'llm_calls': 0,
        'source_roles_retrieved': [r['legal_role'] for r in snapshots],
        'legal_documents_retrieved': len(snapshots),
        'civil_society_posts': len(civil),
        'literal_quotes_verified': len(draft.get('legal_quotes') or []),
        'current_stage_verified': False,
        'visible_length': depth.visible_units(text),
        'validation_issues': issues,
        'coverage': 'partial' if len(snapshots) < len(depth.LEGAL_PAGES) else 'all_legal_pages_read',
        'draft': draft,
        'preview': text,
    }
    Path('mobilization_depth_preview.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in {'draft', 'preview'}}, ensure_ascii=False, indent=2))
    print('--- SOURCE-BOUND PREVIEW; NOT PUBLISHED ---\n' + text)


if __name__ == '__main__':
    main()
