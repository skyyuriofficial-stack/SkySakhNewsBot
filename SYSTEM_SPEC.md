# SkySakhNews stable-v12.0 — production specification

## Invariants

1. Publisher domain is not story geography.
2. Headline and article lead are independently classified.
3. Category is corrected before ranking and rechecked after formatting.
4. Absolute quality threshold is evaluated before proportional balancing.
5. Proportions are maintained over 20 visible, valid posts: 30/20/20/15/10/5.
6. No source photo means no publication; a Telegram delivery failure goes to the persistent retry queue.
7. Russian material uses extractive-first text; foreign material may use OpenRouter translation.
8. Generated title cannot strengthen modality, invent facts or change geography.
9. Every emitted post is audited again after Telegram returns `message_id`.
10. A failed post-audit triggers `deleteMessage`; deleted posts are excluded from the balance.

## Hard rejects

- history/calendar (`В этот день`, anniversaries, archive dates);
- awards, congratulations and ceremonial coverage;
- travel/lifestyle/SEO, recipes, horoscopes and clickbait service content;
- advertorial and partner promotions;
- service notices whose only purpose is returning documents/items;
- routine traffic-enforcement statistics without a casualty/event;
- forums, meetings and exhibitions without a material public decision or consequence.

## Category corrections

- Sakhalin + violence/accident/fire/fraud/hazard → `sakh_chp`;
- Sakhalin + earthquake → `sakh_quake`;
- Sakhalin infrastructure/public services → `sakh`;
- federal banking/economic indicators → `ru_eco` even when syndicated by SakhalinMedia;
- federal law/political decision → `ru_pol`;
- drones/PVO/terrorism/war threats → `ru_security`;
- foreign-state subject → `geo`, or `world_ru` for a world-media story centred on Russia;
- material without a safe stream → reject.

## Quality thresholds

```yaml
local: 70
ru_pol: 76
ru_eco: 76
ru_safety: 78
world: 80
it: 80
```

Quotas never override these thresholds.

## Verification

Production workflow compiles the full chain, runs exact screenshot/feed regressions, publishes through `publisher_v12.py`, runs `post_publish_audit_v12.py`, verifies quality/media/proportion invariants and commits state only after completion.
