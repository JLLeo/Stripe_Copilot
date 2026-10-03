# Golden Set report

Run: 2026-10-01 23:34 UTC · covers the development split (dev), 40 cases

Arms: `decider` = jev-latest at threshold 0.55, margin 0.15, timeout 0.7 s.

Skill selection is the `Skill` calls of a model arm's first response, or the skills the Decider primed. Precision and recall are micro-averaged; a choice among a case's acceptable skills costs nothing. Latency is to the skill decision.

## Skill selection

| Arm | Cell | Cases | Exact | Precision | Recall | F1 | First action | p50 ms | p90 ms | Errors |
|---|---|---|---|---|---|---|---|---|---|---|
| decider | all | 40 | 75% | 93% | 79% | 85% | 90% | 149 | 245 | 0 |
| decider | single_intent_single_turn | 10 | 100% | 100% | 100% | 100% | 100% | 140 | 190 | 0 |
| decider | multi_intent_single_turn | 10 | 60% | 100% | 64% | 78% | 80% | 145 | 230 | 0 |
| decider | single_intent_multi_turn | 10 | 70% | 69% | 100% | 82% | 90% | 176 | 237 | 0 |
| decider | multi_intent_multi_turn | 10 | 70% | 100% | 80% | 89% | 90% | 165 | 261 | 0 |

## Tool selection (model arms)

The tools a model arm calls with the instructions in hand: its first response's tools when it called one a skill informs — *paired* counts those that also loaded a skill, so chose a tool before reading its instructions — otherwise the next response, once those calls are answered. Tools no skill informs (profile, catalogue, remember) are not scored. Latency is to that decision.

| Arm | Cell | Exact | Precision | Recall | F1 | Paired | p50 ms | p90 ms |
|---|---|---|---|---|---|---|---|---|

## Decisions by case

Each arm's skills, ✓ when the set is exact. The Decider shows why it primed nothing.

| Case | Cell | Split | Required skills (+ acceptable) | decider |
|---|---|---|---|---|
| ss-prospect-mobile-grooming | single_intent_single_turn | dev | discovery (+ terminal) | discovery ✓ |
| ss-prospect-cafes-es | single_intent_single_turn | dev | discovery (+ payments) | payments, discovery ✓ |
| ss-offtopic-job-ad | single_intent_single_turn | dev | — | — (below_threshold) ✓ |
| ss-renewals-quietly-lapse | single_intent_single_turn | dev | billing | billing ✓ |
| ss-providers-same-day-pay | single_intent_single_turn | dev | connect | connect ✓ |
| ss-gem-packs-disputed | single_intent_single_turn | dev | fraud_protection | fraud_protection ✓ |
| ss-payouts-provider-objection | single_intent_single_turn | dev | objection_handling (+ connect) | objection_handling ✓ |
| ss-fare-fixed-fee | single_intent_single_turn | dev | pricing_conversation (+ objection_handling) | pricing_conversation, objection_handling ✓ |
| ss-donors-bank-account | single_intent_single_turn | dev | payments | payments ✓ |
| ss-register-30-states | single_intent_single_turn | dev | tax | tax ✓ |
| ms-prospect-yoga-studios | multi_intent_single_turn | dev | discovery, billing, terminal | — (flat) |
| ms-prospect-skincare-zh | multi_intent_single_turn | dev | discovery, payments, fraud_protection | — (flat) |
| ms-1099s-booking-fee-tax | multi_intent_single_turn | dev | connect, tax | tax, connect ✓ |
| ms-residency-snowflake | multi_intent_single_turn | dev | security_compliance, data | security_compliance, data ✓ |
| ms-match-interchange-plus | multi_intent_single_turn | dev | pricing_conversation, objection_handling | pricing_conversation |
| ms-festival-readers-cost | multi_intent_single_turn | dev | terminal, pricing_conversation | terminal |
| ms-ciso-card-data | multi_intent_single_turn | dev | objection_handling, security_compliance | objection_handling, security_compliance ✓ |
| ms-driver-reports-cashout | multi_intent_single_turn | dev | data, connect | connect, data ✓ |
| ms-buses-route-revenue | multi_intent_single_turn | dev | terminal, data | data, terminal ✓ |
| ms-klarna-vip-chargebacks | multi_intent_single_turn | dev | payments, fraud_protection | fraud_protection, payments ✓ |
| sm-bot-then-bakery | single_intent_multi_turn | dev | discovery (+ payments) | discovery, payments ✓ |
| sm-designers-take-a-cut | single_intent_multi_turn | dev | connect | connect ✓ |
| sm-zh-saas-overseas-tax | single_intent_multi_turn | dev | tax (+ billing) | tax, billing ✓ |
| sm-taco-truck-window | single_intent_multi_turn | dev | terminal | terminal, payments |
| sm-spikes-into-bigquery | single_intent_multi_turn | dev | data | data ✓ |
| sm-waive-instant-fee | single_intent_multi_turn | dev | pricing_conversation | pricing_conversation, objection_handling |
| sm-correction-we-pay-shops | single_intent_multi_turn | dev | connect | connect ✓ |
| sm-trade-counter-save-card | single_intent_multi_turn | dev | — | payments, security_compliance |
| sm-backtest-rule | single_intent_multi_turn | dev | — | — (below_threshold) ✓ |
| sm-walk-our-team-through | single_intent_multi_turn | dev | — | — (below_threshold) ✓ |
| mm-offtopic-then-leather | multi_intent_multi_turn | dev | discovery, terminal (+ pricing_conversation, payments) | pricing_conversation |
| mm-es-oxxo-boleto-impuestos | multi_intent_multi_turn | dev | payments, tax | payments, tax ✓ |
| mm-trial-signups-stolen-cards | multi_intent_multi_turn | dev | fraud_protection, billing | fraud_protection |
| mm-listing-fee-and-vendor-payouts | multi_intent_multi_turn | dev | billing, connect | connect |
| mm-one-click-and-method-report | multi_intent_multi_turn | dev | payments, data | payments, data ✓ |
| mm-ca-au-bank-debits | multi_intent_multi_turn | dev | payments, pricing_conversation | pricing_conversation, payments ✓ |
| mm-bank-login-and-instant-verify | multi_intent_multi_turn | dev | security_compliance, payments | security_compliance, payments ✓ |
| mm-dispute-analysis-selective-3ds | multi_intent_multi_turn | dev | data, fraud_protection | fraud_protection, data ✓ |
| mm-ops-meeting-dump | multi_intent_multi_turn | dev | tax, security_compliance | tax, security_compliance ✓ |
| mm-bookkeeper-quickbooks | multi_intent_multi_turn | dev | objection_handling, billing | billing, objection_handling ✓ |
