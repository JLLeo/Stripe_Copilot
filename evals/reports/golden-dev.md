# Golden Set report

Run: 2026-10-01 22:58 UTC · covers the development split (dev), 40 cases

Arms: `main-thinking` = deepseek-v4-pro thinking enabled, `main-no-thinking` = deepseek-v4-pro thinking disabled, `sub-model` = deepseek-flash thinking enabled, `decider` = jev-latest at threshold 0.55, margin 0.15, timeout 0.7 s.

Skill selection is the `Skill` calls of a model arm's first response, or the skills the Decider primed. Precision and recall are micro-averaged; a choice among a case's acceptable skills costs nothing. Latency is to the skill decision.

## Skill selection

| Arm | Cell | Cases | Exact | Precision | Recall | F1 | First action | p50 ms | p90 ms | Errors |
|---|---|---|---|---|---|---|---|---|---|---|
| main-thinking | all | 40 | 92% | 100% | 95% | 97% | 95% | 2,980 | 5,356 | 0 |
| main-thinking | single_intent_single_turn | 10 | 100% | 100% | 100% | 100% | 100% | 2,819 | 3,397 | 0 |
| main-thinking | multi_intent_single_turn | 10 | 90% | 100% | 95% | 98% | 100% | 3,732 | 4,164 | 0 |
| main-thinking | single_intent_multi_turn | 10 | 90% | 100% | 86% | 92% | 80% | 2,216 | 3,477 | 0 |
| main-thinking | multi_intent_multi_turn | 10 | 90% | 100% | 95% | 97% | 100% | 3,435 | 6,071 | 0 |
| main-no-thinking | all | 40 | 50% | 100% | 47% | 64% | 52% | 1,904 | 2,370 | 0 |
| main-no-thinking | single_intent_single_turn | 10 | 60% | 100% | 56% | 71% | 60% | 1,737 | 2,059 | 0 |
| main-no-thinking | multi_intent_single_turn | 10 | 50% | 100% | 64% | 78% | 80% | 1,625 | 1,782 | 0 |
| main-no-thinking | single_intent_multi_turn | 10 | 70% | 100% | 57% | 73% | 50% | 2,025 | 2,342 | 0 |
| main-no-thinking | multi_intent_multi_turn | 10 | 20% | 100% | 20% | 33% | 20% | 2,265 | 2,478 | 0 |
| sub-model | all | 40 | 85% | 95% | 93% | 94% | 98% | 2,018 | 3,512 | 0 |
| sub-model | single_intent_single_turn | 10 | 90% | 92% | 100% | 96% | 100% | 1,842 | 2,326 | 0 |
| sub-model | multi_intent_single_turn | 10 | 80% | 95% | 95% | 95% | 100% | 2,081 | 3,164 | 0 |
| sub-model | single_intent_multi_turn | 10 | 90% | 90% | 100% | 95% | 100% | 1,933 | 2,543 | 0 |
| sub-model | multi_intent_multi_turn | 10 | 80% | 100% | 85% | 92% | 90% | 3,155 | 4,216 | 0 |
| decider | all | 40 | 70% | 89% | 78% | 83% | 90% | 197 | 299 | 0 |
| decider | single_intent_single_turn | 10 | 90% | 91% | 89% | 90% | 90% | 179 | 301 | 0 |
| decider | multi_intent_single_turn | 10 | 50% | 93% | 64% | 76% | 90% | 197 | 244 | 0 |
| decider | single_intent_multi_turn | 10 | 70% | 69% | 100% | 82% | 90% | 187 | 238 | 0 |
| decider | multi_intent_multi_turn | 10 | 70% | 100% | 80% | 89% | 90% | 230 | 280 | 0 |

## Tool selection (model arms)

The tools a model arm calls with the instructions in hand: its first response's tools when it called one a skill informs — *paired* counts those that also loaded a skill, so chose a tool before reading its instructions — otherwise the next response, once those calls are answered. Tools no skill informs (profile, catalogue, remember) are not scored. Latency is to that decision.

| Arm | Cell | Exact | Precision | Recall | F1 | Paired | p50 ms | p90 ms |
|---|---|---|---|---|---|---|---|---|
| main-thinking | all | 45% | 76% | 58% | 66% | 4 | 7,577 | 13,097 |
| main-thinking | single_intent_single_turn | 70% | 83% | 75% | 79% | 1 | 7,099 | 9,395 |
| main-thinking | multi_intent_single_turn | 40% | 75% | 60% | 67% | 2 | 8,254 | 13,732 |
| main-thinking | single_intent_multi_turn | 20% | 56% | 33% | 42% | 0 | 4,730 | 13,097 |
| main-thinking | multi_intent_multi_turn | 50% | 83% | 67% | 74% | 1 | 8,396 | 10,682 |
| main-no-thinking | all | 22% | 53% | 30% | 38% | 4 | 2,478 | 6,431 |
| main-no-thinking | single_intent_single_turn | 20% | 33% | 12% | 18% | 0 | 3,996 | 6,465 |
| main-no-thinking | multi_intent_single_turn | 10% | 50% | 27% | 35% | 2 | 3,570 | 6,699 |
| main-no-thinking | single_intent_multi_turn | 20% | 56% | 25% | 34% | 2 | 2,208 | 3,610 |
| main-no-thinking | multi_intent_multi_turn | 40% | 70% | 47% | 56% | 0 | 2,298 | 5,669 |
| sub-model | all | 45% | 75% | 66% | 70% | 8 | 4,671 | 7,814 |
| sub-model | single_intent_single_turn | 60% | 81% | 88% | 84% | 1 | 4,823 | 7,455 |
| sub-model | multi_intent_single_turn | 40% | 71% | 67% | 69% | 1 | 5,030 | 7,695 |
| sub-model | single_intent_multi_turn | 40% | 62% | 50% | 55% | 2 | 3,829 | 5,436 |
| sub-model | multi_intent_multi_turn | 40% | 83% | 67% | 74% | 4 | 3,994 | 8,604 |

## Decisions by case

Each arm's skills, ✓ when the set is exact. The Decider shows why it primed nothing.

| Case | Cell | Split | Required skills (+ acceptable) | main-thinking | main-no-thinking | sub-model | decider |
|---|---|---|---|---|---|---|---|
| ss-prospect-mobile-grooming | single_intent_single_turn | dev | discovery (+ terminal) | discovery ✓ | — | discovery, payments, terminal | payments |
| ss-prospect-cafes-es | single_intent_single_turn | dev | discovery (+ payments) | discovery, payments ✓ | discovery ✓ | discovery, payments ✓ | payments, discovery ✓ |
| ss-offtopic-job-ad | single_intent_single_turn | dev | — | — ✓ | — ✓ | — ✓ | — (below_threshold) ✓ |
| ss-renewals-quietly-lapse | single_intent_single_turn | dev | billing | billing ✓ | billing ✓ | billing ✓ | billing ✓ |
| ss-providers-same-day-pay | single_intent_single_turn | dev | connect | connect ✓ | connect ✓ | connect ✓ | connect ✓ |
| ss-gem-packs-disputed | single_intent_single_turn | dev | fraud_protection | fraud_protection ✓ | fraud_protection ✓ | fraud_protection ✓ | fraud_protection ✓ |
| ss-payouts-provider-objection | single_intent_single_turn | dev | objection_handling (+ connect) | objection_handling, connect ✓ | connect | objection_handling, connect ✓ | objection_handling ✓ |
| ss-fare-fixed-fee | single_intent_single_turn | dev | pricing_conversation (+ objection_handling) | pricing_conversation ✓ | — | pricing_conversation ✓ | pricing_conversation, objection_handling ✓ |
| ss-donors-bank-account | single_intent_single_turn | dev | payments | payments ✓ | — | payments ✓ | payments ✓ |
| ss-register-30-states | single_intent_single_turn | dev | tax | tax ✓ | tax ✓ | tax ✓ | tax ✓ |
| ms-prospect-yoga-studios | multi_intent_single_turn | dev | discovery, billing, terminal | discovery, billing, terminal ✓ | billing, terminal, discovery ✓ | discovery, billing, terminal ✓ | — (flat) |
| ms-prospect-skincare-zh | multi_intent_single_turn | dev | discovery, payments, fraud_protection | discovery, payments, fraud_protection ✓ | — | discovery, payments, fraud_protection ✓ | fraud_protection |
| ms-1099s-booking-fee-tax | multi_intent_single_turn | dev | connect, tax | connect, tax ✓ | connect, tax ✓ | connect, tax ✓ | tax, connect ✓ |
| ms-residency-snowflake | multi_intent_single_turn | dev | security_compliance, data | security_compliance, data ✓ | security_compliance, data ✓ | security_compliance, data ✓ | security_compliance, data ✓ |
| ms-match-interchange-plus | multi_intent_single_turn | dev | pricing_conversation, objection_handling | pricing_conversation, objection_handling ✓ | pricing_conversation | pricing_conversation, objection_handling, fraud_protection | objection_handling |
| ms-festival-readers-cost | multi_intent_single_turn | dev | terminal, pricing_conversation | terminal | terminal | terminal | terminal |
| ms-ciso-card-data | multi_intent_single_turn | dev | objection_handling, security_compliance | objection_handling, security_compliance ✓ | security_compliance, objection_handling ✓ | objection_handling, security_compliance ✓ | objection_handling, security_compliance ✓ |
| ms-driver-reports-cashout | multi_intent_single_turn | dev | data, connect | connect, data ✓ | connect, data ✓ | data, connect ✓ | connect, data ✓ |
| ms-buses-route-revenue | multi_intent_single_turn | dev | terminal, data | terminal, data ✓ | — | terminal, data ✓ | data, payments |
| ms-klarna-vip-chargebacks | multi_intent_single_turn | dev | payments, fraud_protection | fraud_protection, payments ✓ | fraud_protection | payments, fraud_protection ✓ | fraud_protection, payments ✓ |
| sm-bot-then-bakery | single_intent_multi_turn | dev | discovery (+ payments) | discovery, payments ✓ | — | discovery, payments, terminal | discovery, payments ✓ |
| sm-designers-take-a-cut | single_intent_multi_turn | dev | connect | connect ✓ | connect ✓ | connect ✓ | connect ✓ |
| sm-zh-saas-overseas-tax | single_intent_multi_turn | dev | tax (+ billing) | tax, billing ✓ | tax ✓ | tax, billing ✓ | tax, billing ✓ |
| sm-taco-truck-window | single_intent_multi_turn | dev | terminal | terminal ✓ | terminal ✓ | terminal ✓ | terminal, payments |
| sm-spikes-into-bigquery | single_intent_multi_turn | dev | data | data ✓ | — | data ✓ | data ✓ |
| sm-waive-instant-fee | single_intent_multi_turn | dev | pricing_conversation | — | — | pricing_conversation ✓ | pricing_conversation, objection_handling |
| sm-correction-we-pay-shops | single_intent_multi_turn | dev | connect | connect ✓ | connect ✓ | connect ✓ | connect ✓ |
| sm-trade-counter-save-card | single_intent_multi_turn | dev | — | — ✓ | — ✓ | — ✓ | payments, security_compliance |
| sm-backtest-rule | single_intent_multi_turn | dev | — | — ✓ | — ✓ | — ✓ | — (below_threshold) ✓ |
| sm-walk-our-team-through | single_intent_multi_turn | dev | — | — ✓ | — ✓ | — ✓ | — (below_threshold) ✓ |
| mm-offtopic-then-leather | multi_intent_multi_turn | dev | discovery, terminal (+ pricing_conversation, payments) | discovery, pricing_conversation, terminal ✓ | — | discovery, payments, terminal, pricing_conversation ✓ | pricing_conversation |
| mm-es-oxxo-boleto-impuestos | multi_intent_multi_turn | dev | payments, tax | payments, tax ✓ | — | — | payments, tax ✓ |
| mm-trial-signups-stolen-cards | multi_intent_multi_turn | dev | fraud_protection, billing | billing, fraud_protection ✓ | billing, fraud_protection ✓ | fraud_protection, billing ✓ | billing |
| mm-listing-fee-and-vendor-payouts | multi_intent_multi_turn | dev | billing, connect | connect, billing ✓ | billing, connect ✓ | connect, billing ✓ | connect |
| mm-one-click-and-method-report | multi_intent_multi_turn | dev | payments, data | payments, data ✓ | — | payments, data ✓ | payments, data ✓ |
| mm-ca-au-bank-debits | multi_intent_multi_turn | dev | payments, pricing_conversation | payments, pricing_conversation ✓ | — | payments, pricing_conversation ✓ | pricing_conversation, payments ✓ |
| mm-bank-login-and-instant-verify | multi_intent_multi_turn | dev | security_compliance, payments | security_compliance | — | security_compliance | security_compliance, payments ✓ |
| mm-dispute-analysis-selective-3ds | multi_intent_multi_turn | dev | data, fraud_protection | data, fraud_protection ✓ | — | data, fraud_protection ✓ | fraud_protection, data ✓ |
| mm-ops-meeting-dump | multi_intent_multi_turn | dev | tax, security_compliance | tax, security_compliance ✓ | — | tax, security_compliance ✓ | tax, security_compliance ✓ |
| mm-bookkeeper-quickbooks | multi_intent_multi_turn | dev | objection_handling, billing | billing, objection_handling ✓ | — | billing, objection_handling ✓ | billing, objection_handling ✓ |
