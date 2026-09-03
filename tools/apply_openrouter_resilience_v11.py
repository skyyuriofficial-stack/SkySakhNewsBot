#!/usr/bin/env python3
# Apply the stable-v11.0 OpenRouter resilience hotfix.
#
# This file is used once by a temporary branch workflow. It patches the current
# production sources, adds regression coverage, and is deleted before the branch
# is merged.

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one exact match, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, *, label: str) -> str:
    compiled = re.compile(pattern, re.S)
    updated, count = compiled.subn(lambda _: replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"{label}: expected one regex match, found {count}")
    return updated


def patch_editorial_runner() -> None:
    path = "src/editorial_gate_runner.py"
    text = read(path)

    text = replace_once(
        text,
        "import os\nfrom typing import Any, Dict, Optional",
        "import os\nimport random\nimport time\nfrom typing import Any, Dict, Optional",
        label=f"{path} imports",
    )

    text = replace_once(
        text,
        '    "openrouter_empty_content",\n'
        '    "openrouter_model_fallback",\n',
        '    "openrouter_empty_content",\n'
        '    "openrouter_model_fallback",\n'
        '    "openrouter_attempts",\n'
        '    "openrouter_retries",\n'
        '    "openrouter_invalid_json",\n'
        '    "openrouter_success",\n'
        '    "openrouter_circuit_open",\n',
        label=f"{path} OpenRouter stats",
    )

    replacement = r'''_OPENROUTER_CIRCUIT_OPEN = False
_OPENROUTER_CIRCUIT_REASON = ""


def _openrouter_model_plan():
    "Build a bounded plan without silently switching to a paid model."
    raw_primary = os.getenv("OPENROUTER_MODEL", "").strip()
    raw_fallbacks = os.getenv("OPENROUTER_FALLBACK_MODELS", "").strip()
    configured = [
        value.strip()
        for value in (raw_primary + "," + raw_fallbacks).split(",")
        if value.strip()
    ]
    try:
        max_attempts = int(os.getenv("OPENROUTER_MAX_ATTEMPTS", "3"))
    except ValueError:
        max_attempts = 3
    max_attempts = max(1, min(6, max_attempts))

    plan = []
    for model in configured:
        if model not in plan:
            plan.append(model)
    if not plan:
        plan.append("openrouter/free")

    # Repeated calls to openrouter/free are intentional: every request can be
    # routed to a different currently available free model.
    while len(plan) < max_attempts:
        plan.append("openrouter/free")
    return plan[:max_attempts]


def _retry_delay_seconds(response, attempt):
    headers = getattr(response, "headers", {}) or {}
    retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if retry_after:
        try:
            return max(0.0, min(15.0, float(retry_after)))
        except (TypeError, ValueError):
            pass

    try:
        base = float(os.getenv("OPENROUTER_RETRY_BASE_SECONDS", "1.0"))
    except ValueError:
        base = 1.0
    base = max(0.0, min(5.0, base))
    jitter = 0.0 if base == 0 else random.uniform(0.0, min(0.35, base / 2))
    return min(12.0, base * (2 ** attempt) + jitter)


def _is_json_object(text):
    try:
        return isinstance(core.b.parse_obj(text), dict)
    except Exception:
        return False


def resilient_openrouter(messages, max_tokens=1100):
    global _OPENROUTER_CIRCUIT_OPEN, _OPENROUTER_CIRCUIT_REASON

    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is missing")
    if _OPENROUTER_CIRCUIT_OPEN:
        raise RuntimeError(
            "OpenRouter circuit is open for this run: "
            + (_OPENROUTER_CIRCUIT_REASON or "previous attempts failed")
        )

    plan = _openrouter_model_plan()
    errors = []

    for attempt, model in enumerate(plan):
        core.b.STATS["openrouter_attempts"] += 1
        response = None
        stop_immediately = False

        try:
            response = core.b.requests.post(
                core.b.OPENROUTER_URL,
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://t.me/SkySakhNews",
                    "X-OpenRouter-Title": "SkySakhNews",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "stream": False,
                    "response_format": {"type": "json_object"},
                    "provider": {
                        "require_parameters": True,
                        "allow_fallbacks": True,
                    },
                },
                timeout=90,
            )

            if response.status_code >= 400:
                detail = (response.text or "")[:300]
                errors.append(f"{model}: HTTP {response.status_code}: {detail}")
                if response.status_code in {401, 403}:
                    stop_immediately = True
            else:
                payload = response.json()
                if not isinstance(payload, dict):
                    errors.append(f"{model}: response is not an object")
                elif payload.get("error"):
                    errors.append(f"{model}: API error: {str(payload.get('error'))[:300]}")
                else:
                    choices = payload.get("choices")
                    if not isinstance(choices, list) or not choices:
                        errors.append(f"{model}: missing choices")
                    else:
                        first = choices[0] if isinstance(choices[0], dict) else {}
                        text = _message_text(first.get("message"))
                        if not text:
                            alternative = first.get("text")
                            if isinstance(alternative, str) and alternative.strip():
                                text = alternative.strip()

                        if not text:
                            core.b.STATS["openrouter_empty_content"] += 1
                            errors.append(f"{model}: empty message content")
                        elif not _is_json_object(text):
                            core.b.STATS["openrouter_invalid_json"] += 1
                            errors.append(f"{model}: invalid JSON object")
                        else:
                            used_model = str(payload.get("model") or model)
                            core.b.STATS["openrouter_success"] += 1
                            if attempt > 0:
                                core.b.STATS["openrouter_model_fallback"] += 1
                            core.b.log(
                                "OpenRouter JSON accepted: "
                                f"{used_model} (attempt {attempt + 1}/{len(plan)})"
                            )
                            return text
        except Exception as exc:
            errors.append(
                f"{model}: {type(exc).__name__}: {str(exc)[:300]}"
            )

        if stop_immediately:
            break
        if attempt + 1 < len(plan):
            core.b.STATS["openrouter_retries"] += 1
            delay = _retry_delay_seconds(response, attempt)
            if delay > 0:
                time.sleep(delay)

    _OPENROUTER_CIRCUIT_OPEN = True
    _OPENROUTER_CIRCUIT_REASON = " | ".join(errors[-4:]) or "unknown failure"
    core.b.STATS["openrouter_circuit_open"] = 1
    raise RuntimeError("OpenRouter failed: " + _OPENROUTER_CIRCUIT_REASON)'''

    text = regex_once(
        text,
        r"def resilient_openrouter\(messages, max_tokens=1100\):\n.*?\n\n\ncore\.b\.openrouter = resilient_openrouter",
        replacement + "\n\n\ncore.b.openrouter = resilient_openrouter",
        label=f"{path} resilient_openrouter",
    )
    write(path, text)


def patch_production() -> None:
    path = "src/production.py"
    text = read(path)

    text = replace_once(
        text,
        'AI_CALL_BUDGET = max(0, int(os.getenv("AI_CALL_BUDGET", "8")))' ,
        'AI_CALL_BUDGET = max(0, int(os.getenv("AI_CALL_BUDGET", "4")))' ,
        label=f"{path} default AI budget",
    )

    text = replace_once(
        text,
        '    "validation_reject", "extractive_fallback",\n',
        '    "validation_reject", "extractive_fallback", "extractive_first",\n',
        label=f"{path} extractive stats",
    )

    text = replace_once(
        text,
        '        "temporarily unavailable", "timeout", "timed out", "502", "503", "504",\n',
        '        "temporarily unavailable", "timeout", "timed out", "502", "503", "504",\n'
        '        "openrouter failed", "circuit is open",\n',
        label=f"{path} systemic OpenRouter errors",
    )

    replacement = r'''def valid_post_v99(c):
    global _AI_CALLS, _AI_CIRCUIT_OPEN
    last_error = ""
    attempts = 0

    # Russian-language articles do not need an LLM rewrite. Publishing two
    # exact, validated source sentences is both safer and substantially more
    # reliable than spending free-model quota on stylistic paraphrasing.
    fallback = _extractive_fallback(c)
    if fallback:
        core.b.STATS["extractive_fallback"] += 1
        core.b.STATS["extractive_first"] += 1
        core.b.log(f"extractive-first accepted: {c['title'][:80]}")
        return fallback

    while attempts < 2 and not _AI_CIRCUIT_OPEN and _AI_CALLS < AI_CALL_BUDGET:
        attempts += 1
        _AI_CALLS += 1
        core.b.STATS["ai_calls"] = _AI_CALLS
        try:
            row = core.generate_grounded(c, last_error)
            errors = _validate_generated_v99(row, c)
            if not errors:
                return row
            core.b.STATS["validation_reject"] += 1
            last_error = "; ".join(errors)[:500]
            core.b.STATS["rewrite_retry"] += 1
            core.b.log(f"rewrite required: {c['title'][:70]} | {last_error}")
        except Exception as ex:
            core.b.STATS["ai_api_fail"] += 1
            core.b.STATS["rewrite_retry"] += 1
            last_error = str(ex)[:500]
            core.b.log(f"AI generation failed: {c['title'][:70]} | {last_error}")
            if _api_failure_is_systemic(ex):
                _AI_CIRCUIT_OPEN = True
                core.b.log(
                    "AI circuit opened for this run; candidates without a safe "
                    "extractive post will be skipped"
                )
                break

    if _AI_CALLS >= AI_CALL_BUDGET:
        core.b.STATS["ai_budget_exhausted"] = 1

    core.b.STATS["editorial_skip"] += 1
    return None'''

    text = regex_once(
        text,
        r"def valid_post_v99\(c\):\n.*?\n\n\ncore\.b\.valid_post = valid_post_v99",
        replacement + "\n\n\ncore.b.valid_post = valid_post_v99",
        label=f"{path} valid_post_v99",
    )
    write(path, text)


def patch_publisher() -> None:
    path = "src/publisher.py"
    text = read(path)

    text = replace_once(
        text,
        'DIRECTOR_AI_BUDGET = max(0, int(os.getenv("NEWS_DIRECTOR_AI_BUDGET", "1")))' ,
        'DIRECTOR_AI_BUDGET = max(0, int(os.getenv("NEWS_DIRECTOR_AI_BUDGET", "0")))' ,
        label=f"{path} default director AI budget",
    )

    text = replace_once(
        text,
        '    "director_pending_retired",\n',
        '    "director_pending_retired",\n'
        '    "director_deterministic_fallback",\n',
        label=f"{path} director stats",
    )

    marker = '''    core.b.STATS.setdefault(key, 0)


def _director_ai_review(
'''
    replacement = '''    core.b.STATS.setdefault(key, 0)


# The deterministic director is authoritative. OpenRouter is an optional veto,
# never a single point of failure that can erase otherwise valid candidates.
_original_apply_ai_review = director._apply_ai_review


def _apply_ai_review_optional(review, ai):
    if ai is None:
        if review.get("needs_ai_review"):
            core.b.STATS["director_deterministic_fallback"] += 1
            review["ai_review_status"] = "unavailable_deterministic_policy"
        return review
    return _original_apply_ai_review(review, ai)


director._apply_ai_review = _apply_ai_review_optional


def _director_ai_review(
'''
    text = replace_once(
        text,
        marker,
        replacement,
        label=f"{path} optional director AI",
    )
    write(path, text)


def patch_editorial_policy() -> None:
    path = "src/editorial_gate_runner.py"
    text = read(path)

    text = replace_once(
        text,
        'AI_AUDIT_BUDGET = max(0, int(os.getenv("EDITORIAL_AUDIT_AI_BUDGET", "4")))' ,
        'AI_AUDIT_BUDGET = max(0, int(os.getenv("EDITORIAL_AUDIT_AI_BUDGET", "2")))' ,
        label=f"{path} default editorial AI budget",
    )

    old = '''    if not deterministic.get("requires_ai_review"):
        deterministic["approved"] = (
            bool(deterministic.get("approved"))
            and int(deterministic.get("title_matches_source") or 0) >= 90
            and int(deterministic.get("category_matches_story") or 0) >= 90
            and deterministic.get("facts_supported") is True
            and deterministic.get("meaning_changed") is False
        )
        return deterministic

    merged = gate.merge_reviews(deterministic, _independent_ai_review(candidate, row))
'''
    new = '''    deterministic_pass = (
        bool(deterministic.get("approved"))
        and int(deterministic.get("title_matches_source") or 0) >= 90
        and int(deterministic.get("category_matches_story") or 0) >= 90
        and deterministic.get("facts_supported") is True
        and deterministic.get("meaning_changed") is False
    )

    # An exact Russian extract contains no LLM paraphrase to audit. If every
    # deterministic invariant already passes, an external model adds latency
    # and failure risk without adding factual protection.
    if (
        row.get("editorial_mode") == "extractive_fallback"
        and deterministic.get("source_is_russian") is True
        and deterministic_pass
    ):
        deterministic["approved"] = True
        deterministic["requires_ai_review"] = False
        deterministic["mode"] = "deterministic+extractive"
        return deterministic

    if not deterministic.get("requires_ai_review"):
        deterministic["approved"] = deterministic_pass
        return deterministic

    merged = gate.merge_reviews(deterministic, _independent_ai_review(candidate, row))
'''
    text = replace_once(
        text,
        old,
        new,
        label=f"{path} extractive editorial policy",
    )
    write(path, text)


def patch_selftest() -> None:
    path = "src/production_selftest.py"
    text = read(path)

    text = replace_once(
        text,
        "from __future__ import annotations\n\nfrom datetime",
        "from __future__ import annotations\n\nimport os\nfrom datetime",
        label=f"{path} os import",
    )
    text = replace_once(
        text,
        "import editorial_gate as gate\n",
        "import editorial_gate as gate\nimport editorial_gate_runner as editorial\n",
        label=f"{path} editorial runner import",
    )

    tests = r'''


def openrouter_resilience_regression():
    class FakeResponse:
        def __init__(self, payload, status_code=200, text=""):
            self._payload = payload
            self.status_code = status_code
            self.text = text
            self.headers = {}

        def json(self):
            return self._payload

    responses = [
        FakeResponse({
            "model": "free/empty",
            "choices": [{"message": {"content": ""}}],
        }),
        FakeResponse({
            "model": "free/invalid",
            "choices": [{"message": {"content": "not-json"}}],
        }),
        FakeResponse({
            "model": "free/valid",
            "choices": [{"message": {"content": '{"ok": true}'}}],
        }),
    ]
    calls = []

    def fake_post(url, **kwargs):
        assert url == editorial.core.b.OPENROUTER_URL
        calls.append(kwargs)
        return responses.pop(0)

    env_names = (
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
        "OPENROUTER_FALLBACK_MODELS",
        "OPENROUTER_MAX_ATTEMPTS",
        "OPENROUTER_RETRY_BASE_SECONDS",
    )
    saved_env = {name: os.environ.get(name) for name in env_names}
    saved_post = editorial.core.b.requests.post
    saved_circuit = editorial._OPENROUTER_CIRCUIT_OPEN
    saved_reason = editorial._OPENROUTER_CIRCUIT_REASON
    stat_names = (
        "openrouter_empty_content",
        "openrouter_model_fallback",
        "openrouter_attempts",
        "openrouter_retries",
        "openrouter_invalid_json",
        "openrouter_success",
        "openrouter_circuit_open",
    )
    saved_stats = {
        name: editorial.core.b.STATS.get(name)
        for name in stat_names
    }

    try:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        os.environ["OPENROUTER_MODEL"] = ""
        os.environ["OPENROUTER_FALLBACK_MODELS"] = ""
        os.environ["OPENROUTER_MAX_ATTEMPTS"] = "3"
        os.environ["OPENROUTER_RETRY_BASE_SECONDS"] = "0"
        editorial._OPENROUTER_CIRCUIT_OPEN = False
        editorial._OPENROUTER_CIRCUIT_REASON = ""
        editorial.core.b.requests.post = fake_post
        for name in stat_names:
            editorial.core.b.STATS[name] = 0

        assert publisher.core.b.openrouter is editorial.resilient_openrouter
        raw = publisher.core.b.openrouter(
            [{"role": "user", "content": "Верни JSON"}],
            max_tokens=128,
        )
        assert publisher.core.b.parse_obj(raw) == {"ok": True}
        assert len(calls) == 3
        for call in calls:
            body = call["json"]
            assert body["model"] == "openrouter/free"
            assert body["response_format"] == {"type": "json_object"}
            assert body["provider"]["require_parameters"] is True
            assert body["provider"]["allow_fallbacks"] is True
            assert "temperature" not in body
        assert editorial.core.b.STATS["openrouter_empty_content"] == 1
        assert editorial.core.b.STATS["openrouter_invalid_json"] == 1
        assert editorial.core.b.STATS["openrouter_attempts"] == 3
        assert editorial.core.b.STATS["openrouter_retries"] == 2
        assert editorial.core.b.STATS["openrouter_success"] == 1
        assert editorial.core.b.STATS["openrouter_model_fallback"] == 1
        assert editorial._OPENROUTER_CIRCUIT_OPEN is False
    finally:
        editorial.core.b.requests.post = saved_post
        editorial._OPENROUTER_CIRCUIT_OPEN = saved_circuit
        editorial._OPENROUTER_CIRCUIT_REASON = saved_reason
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        for name, value in saved_stats.items():
            if value is None:
                editorial.core.b.STATS.pop(name, None)
            else:
                editorial.core.b.STATS[name] = value


def extractive_first_regression():
    item = candidate(
        "В Южно-Сахалинске временно изменили схему движения автобусов",
        (
            "Администрация Южно-Сахалинска сообщила, что с понедельника движение "
            "автобусов по улице Ленина будет организовано по временной схеме. "
            "Изменение связано с ремонтом дорожного покрытия и будет действовать "
            "до завершения работ на указанном участке."
        ),
        url="https://sakhalinmedia.ru/news/extractive-first/",
    )

    called = {"value": False}
    original_generate = publisher.prod.core.generate_grounded
    original_extract_count = publisher.core.b.STATS.get("extractive_fallback")
    original_first_count = publisher.core.b.STATS.get("extractive_first")

    def unexpected_generate(*args, **kwargs):
        called["value"] = True
        raise AssertionError("Russian extractive post must not call OpenRouter")

    try:
        publisher.prod.core.generate_grounded = unexpected_generate
        publisher.core.b.STATS["extractive_fallback"] = 0
        publisher.core.b.STATS["extractive_first"] = 0
        row = publisher.prod.valid_post_v99(item)
        assert row is not None
        assert row.get("editorial_mode") == "extractive_fallback"
        assert called["value"] is False
        assert publisher.core.b.STATS["extractive_first"] == 1
    finally:
        publisher.prod.core.generate_grounded = original_generate
        if original_extract_count is None:
            publisher.core.b.STATS.pop("extractive_fallback", None)
        else:
            publisher.core.b.STATS["extractive_fallback"] = original_extract_count
        if original_first_count is None:
            publisher.core.b.STATS.pop("extractive_first", None)
        else:
            publisher.core.b.STATS["extractive_first"] = original_first_count


def director_ai_outage_regression():
    borderline = candidate(
        "На Сахалине изменили график работы областной библиотеки",
        "Новый график действует для посетителей учреждения до конца месяца.",
        url="https://sakhalinmedia.ru/news/director-ai-outage/",
        category="sakh",
        score=100,
    )
    initial = director.review_candidate(borderline)
    assert initial["approved"] is True, initial
    assert initial["needs_ai_review"] is True, initial
    assert initial["seriousness"] < initial["threshold"] + 4, initial

    ordered, report = director.direct_candidates(
        {"last_posts": []},
        [borderline],
        category_map=publisher.core.b.CAT,
        now=datetime(2026, 9, 4, 7, 0, tzinfo=timezone(timedelta(hours=11))),
        ai_reviewer=lambda _: {},
    )
    assert [item["url"] for item in ordered] == [borderline["url"]], report
    final = report["by_url"][borderline["url"]]
    assert final["approved"] is True, final
    assert final["reason"] == "approved", final
'''

    text = replace_once(
        text,
        "\ndef media_and_version_regressions():\n",
        tests + "\n\ndef media_and_version_regressions():\n",
        label=f"{path} resilience tests",
    )

    text = replace_once(
        text,
        '''    repetitive_subtype_regression()
    media_and_version_regressions()
''',
        '''    repetitive_subtype_regression()
    openrouter_resilience_regression()
    extractive_first_regression()
    director_ai_outage_regression()
    media_and_version_regressions()
''',
        label=f"{path} main tests",
    )
    write(path, text)


def patch_workflow(path: str) -> None:
    text = read(path)
    text = text.replace('AI_CALL_BUDGET: "8"', 'AI_CALL_BUDGET: "4"')
    text = text.replace(
        'EDITORIAL_AUDIT_AI_BUDGET: "4"',
        'EDITORIAL_AUDIT_AI_BUDGET: "2"',
    )
    text = text.replace(
        'NEWS_DIRECTOR_AI_BUDGET: "1"',
        'NEWS_DIRECTOR_AI_BUDGET: "0"',
    )

    marker = '          NEWS_DIRECTOR_AI_BUDGET: "0"\n'
    addition = (
        marker
        + '          OPENROUTER_MAX_ATTEMPTS: "3"\n'
        + '          OPENROUTER_RETRY_BASE_SECONDS: "1.0"\n'
    )
    if "OPENROUTER_MAX_ATTEMPTS" not in text:
        text = text.replace(marker, addition)
    write(path, text)


def main() -> None:
    patch_editorial_runner()
    patch_production()
    patch_publisher()
    patch_editorial_policy()
    patch_selftest()
    patch_workflow(".github/workflows/auto_publish_v7.yml")
    patch_workflow(".github/workflows/production_ci.yml")
    print("OpenRouter resilience hotfix applied")


if __name__ == "__main__":
    main()
