#!/usr/bin/env python3
import apply_final_title_v121 as base

base.main()
base.replace_once(
    "src/production_selftest.py",
    '    assert policy.VERSION == "policy-v2.2"',
    '    assert policy.VERSION == "policy-v2.3"',
)
print("final title v12.1 v2 patch applied")
