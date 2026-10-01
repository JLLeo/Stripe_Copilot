# Golden Set report

Run: 2026-10-01 22:57 UTC · covers the held-out split (test), 40 cases

Arms: `main-thinking` = deepseek-v4-pro thinking enabled, `main-no-thinking` = deepseek-v4-pro thinking disabled, `sub-model` = deepseek-flash thinking enabled, `decider` = jev-latest at threshold 0.55, margin 0.15, timeout 0.7 s.

Skill selection is the `Skill` calls of a model arm's first response, or the skills the Decider primed. Precision and recall are micro-averaged; a choice among a case's acceptable skills costs nothing. Latency is to the skill decision.

## Skill selection

| Arm | Cell | Cases | Exact | Precision | Recall | F1 | First action | p50 ms | p90 ms | Errors |
|---|---|---|---|---|---|---|---|---|---|---|
| main-thinking | all | 40 | 75% | 100% | 81% | 89% | 88% | 2,806 | 5,987 | 0 |
| main-thinking | single_intent_single_turn | 10 | 80% | 100% | 78% | 88% | 80% | 2,895 | 6,313 | 0 |
| main-thinking | multi_intent_single_turn | 10 | 80% | 100% | 91% | 95% | 100% | 3,187 | 5,240 | 0 |
| main-thinking | single_intent_multi_turn | 10 | 80% | 100% | 67% | 80% | 80% | 1,842 | 5,171 | 0 |
| main-thinking | multi_intent_multi_turn | 10 | 60% | 100% | 75% | 86% | 90% | 2,600 | 5,987 | 0 |
| main-no-thinking | all | 40 | 52% | 100% | 58% | 73% | 57% | 1,826 | 2,854 | 0 |
| main-no-thinking | single_intent_single_turn | 10 | 60% | 100% | 56% | 71% | 60% | 1,618 | 1,942 | 0 |
| main-no-thinking | multi_intent_single_turn | 10 | 70% | 100% | 82% | 90% | 90% | 1,658 | 2,061 | 0 |
| main-no-thinking | single_intent_multi_turn | 10 | 50% | 100% | 17% | 29% | 20% | 1,999 | 2,895 | 0 |
| main-no-thinking | multi_intent_multi_turn | 10 | 30% | 100% | 45% | 62% | 60% | 1,826 | 2,930 | 0 |
| sub-model | all | 40 | 92% | 98% | 96% | 97% | 98% | 1,928 | 3,289 | 0 |
| sub-model | single_intent_single_turn | 10 | 90% | 100% | 89% | 94% | 90% | 1,650 | 3,460 | 0 |
| sub-model | multi_intent_single_turn | 10 | 100% | 100% | 100% | 100% | 100% | 1,771 | 2,662 | 0 |
| sub-model | single_intent_multi_turn | 10 | 90% | 86% | 100% | 92% | 100% | 1,928 | 3,289 | 0 |
| sub-model | multi_intent_multi_turn | 10 | 90% | 100% | 95% | 97% | 100% | 2,026 | 2,572 | 0 |
| decider | all | 40 | 68% | 92% | 79% | 85% | 95% | 178 | 228 | 0 |
| decider | single_intent_single_turn | 10 | 70% | 85% | 89% | 87% | 90% | 178 | 235 | 0 |
| decider | multi_intent_single_turn | 10 | 50% | 100% | 68% | 81% | 90% | 196 | 208 | 0 |
| decider | single_intent_multi_turn | 10 | 90% | 86% | 100% | 92% | 100% | 172 | 199 | 0 |
| decider | multi_intent_multi_turn | 10 | 60% | 94% | 80% | 86% | 100% | 166 | 221 | 0 |

## Tool selection (model arms)

The tools a model arm calls with the instructions in hand: its first response's tools when it called one a skill informs — *paired* counts those that also loaded a skill, so chose a tool before reading its instructions — otherwise the next response, once those calls are answered. Tools no skill informs (profile, catalogue, remember) are not scored. Latency is to that decision.

| Arm | Cell | Exact | Precision | Recall | F1 | Paired | p50 ms | p90 ms |
|---|---|---|---|---|---|---|---|---|
| main-thinking | all | 50% | 69% | 73% | 71% | 10 | 5,694 | 11,036 |
| main-thinking | single_intent_single_turn | 80% | 82% | 90% | 86% | 4 | 4,216 | 11,036 |
| main-thinking | multi_intent_single_turn | 20% | 62% | 71% | 67% | 2 | 7,811 | 9,323 |
| main-thinking | single_intent_multi_turn | 80% | 88% | 88% | 88% | 0 | 2,592 | 17,206 |
| main-thinking | multi_intent_multi_turn | 20% | 54% | 54% | 54% | 4 | 5,593 | 8,741 |
| main-no-thinking | all | 32% | 52% | 31% | 39% | 7 | 2,714 | 6,048 |
| main-no-thinking | single_intent_single_turn | 70% | 70% | 70% | 70% | 2 | 1,942 | 3,486 |
| main-no-thinking | multi_intent_single_turn | 10% | 25% | 14% | 18% | 2 | 4,695 | 7,138 |
| main-no-thinking | single_intent_multi_turn | 30% | 60% | 12% | 21% | 1 | 1,999 | 2,895 |
| main-no-thinking | multi_intent_multi_turn | 20% | 50% | 31% | 38% | 2 | 2,434 | 5,655 |
| sub-model | all | 40% | 65% | 71% | 68% | 6 | 4,446 | 6,477 |
| sub-model | single_intent_single_turn | 70% | 77% | 90% | 83% | 2 | 4,742 | 6,040 |
| sub-model | multi_intent_single_turn | 20% | 65% | 71% | 68% | 0 | 4,446 | 6,477 |
| sub-model | single_intent_multi_turn | 50% | 71% | 88% | 79% | 2 | 2,332 | 8,916 |
| sub-model | multi_intent_multi_turn | 20% | 46% | 46% | 46% | 2 | 4,603 | 5,412 |

## Decisions by case

Each arm's skills, ✓ when the set is exact. The Decider shows why it primed nothing.

| Case | Cell | Split | Required skills (+ acceptable) | main-thinking | main-no-thinking | sub-model | decider |
|---|---|---|---|---|---|---|---|
| ss-prospect-card-fee-first | single_intent_single_turn | test | discovery (+ pricing_conversation) | pricing_conversation | — | pricing_conversation, discovery ✓ | pricing_conversation |
| ss-prospect-45m-call | single_intent_single_turn | test | discovery | discovery ✓ | — | discovery ✓ | payments, discovery |
| ss-person-video-call | single_intent_single_turn | test | — | — ✓ | — ✓ | — ✓ | — (below_threshold) ✓ |
| ss-prepaid-credits-january | single_intent_single_turn | test | billing | billing ✓ | billing ✓ | billing ✓ | billing ✓ |
| ss-month-end-netsuite | single_intent_single_turn | test | data (+ billing) | data, billing ✓ | data ✓ | data, billing ✓ | data ✓ |
| ss-good-buyers-blocked | single_intent_single_turn | test | fraud_protection (+ payments) | fraud_protection ✓ | fraud_protection ✓ | fraud_protection ✓ | fraud_protection, payments ✓ |
| ss-tap-to-pay-fee | single_intent_single_turn | test | pricing_conversation (+ terminal) | terminal | — | terminal | pricing_conversation ✓ |
| ss-dutch-belgian-methods | single_intent_single_turn | test | payments | payments ✓ | payments ✓ | payments ✓ | payments ✓ |
| ss-elements-pci-scope | single_intent_single_turn | test | security_compliance (+ payments) | security_compliance ✓ | payments | security_compliance, payments ✓ | security_compliance, payments ✓ |
| ss-singapore-stores-zh | single_intent_single_turn | test | terminal | terminal ✓ | terminal ✓ | terminal ✓ | terminal, payments |
| ms-prospect-tutoring-es | multi_intent_single_turn | test | discovery, connect (+ pricing_conversation) | discovery, connect, pricing_conversation ✓ | connect, discovery ✓ | discovery, connect ✓ | connect |
| ms-prospect-hr-soc2-invoices | multi_intent_single_turn | test | discovery, security_compliance, billing | discovery, billing, security_compliance ✓ | discovery, billing | discovery, security_compliance, billing ✓ | security_compliance, billing |
| ms-eu-vat-euro-plans | multi_intent_single_turn | test | tax, billing (+ payments) | tax, billing ✓ | tax, billing ✓ | tax, billing ✓ | tax |
| ms-dashboard-queries-proration | multi_intent_single_turn | test | data, billing | data, billing ✓ | data, billing ✓ | data, billing ✓ | billing, data ✓ |
| ms-market-stall-qr-orders | multi_intent_single_turn | test | terminal, payments | terminal, payments ✓ | terminal, payments ✓ | terminal, payments ✓ | payments, terminal ✓ |
| ms-fake-sellers-stolen-cards | multi_intent_single_turn | test | connect, fraud_protection | connect, fraud_protection ✓ | connect, fraud_protection ✓ | fraud_protection, connect ✓ | fraud_protection, connect ✓ |
| ms-checkout-pci-sales-tax | multi_intent_single_turn | test | security_compliance, tax (+ payments) | payments, tax | — | security_compliance, tax ✓ | tax |
| ms-card-testing-fraud-teams | multi_intent_single_turn | test | fraud_protection, pricing_conversation | fraud_protection | fraud_protection | fraud_protection, pricing_conversation ✓ | fraud_protection, pricing_conversation ✓ |
| ms-course-platform-ramble | multi_intent_single_turn | test | connect, tax, billing | connect, tax, billing ✓ | connect, billing, tax ✓ | billing, connect, tax ✓ | — (flat) |
| ms-too-technical-currencies | multi_intent_single_turn | test | objection_handling, payments | objection_handling, payments ✓ | objection_handling, payments ✓ | objection_handling, payments ✓ | payments, objection_handling ✓ |
| sm-applepay-on-top | single_intent_multi_turn | test | pricing_conversation | — | — | pricing_conversation ✓ | pricing_conversation ✓ |
| sm-donors-monthly-gift | single_intent_multi_turn | test | billing | billing ✓ | billing ✓ | billing ✓ | billing ✓ |
| sm-branded-checkout-no-code | single_intent_multi_turn | test | payments | — | — | payments ✓ | payments ✓ |
| sm-patient-invoices-hipaa | single_intent_multi_turn | test | security_compliance | security_compliance ✓ | — | security_compliance ✓ | security_compliance ✓ |
| sm-dunning-tool-rant | single_intent_multi_turn | test | objection_handling | objection_handling ✓ | — | objection_handling ✓ | objection_handling ✓ |
| sm-es-tarjetas-robadas | single_intent_multi_turn | test | fraud_protection | fraud_protection ✓ | — | fraud_protection, payments | fraud_protection, security_compliance |
| sm-pause-ends | single_intent_multi_turn | test | — | — ✓ | — ✓ | — ✓ | — (below_threshold) ✓ |
| sm-caregiver-verification-time | single_intent_multi_turn | test | — | — ✓ | — ✓ | — ✓ | — (below_threshold) ✓ |
| sm-candles-monthly-cost | single_intent_multi_turn | test | — | — ✓ | — ✓ | — ✓ | — (below_threshold) ✓ |
| sm-offtopic-product-names | single_intent_multi_turn | test | — | — ✓ | — ✓ | — ✓ | — (below_threshold) ✓ |
| mm-zh-disputes-and-front-desk | multi_intent_multi_turn | test | fraud_protection, terminal | fraud_protection, terminal ✓ | fraud_protection, terminal ✓ | fraud_protection, terminal ✓ | fraud_protection, terminal ✓ |
| mm-fraud-vendor-and-disputes | multi_intent_multi_turn | test | objection_handling, fraud_protection | fraud_protection, objection_handling ✓ | fraud_protection | objection_handling, fraud_protection ✓ | fraud_protection, objection_handling ✓ |
| mm-eu-tax-cost-and-registration | multi_intent_multi_turn | test | pricing_conversation, tax | tax | tax | tax | tax, pricing_conversation ✓ |
| mm-warehouse-counters-sales-tax | multi_intent_multi_turn | test | terminal, tax | terminal, tax ✓ | terminal, tax ✓ | terminal, tax ✓ | tax |
| mm-onsite-cut-and-bank-transfer | multi_intent_multi_turn | test | connect, payments | connect, payments ✓ | — | connect, payments ✓ | connect, pricing_conversation |
| mm-bank-terminals-objection | multi_intent_multi_turn | test | objection_handling, terminal | terminal | terminal | terminal, objection_handling ✓ | objection_handling |
| mm-au-residency-new-countries | multi_intent_multi_turn | test | security_compliance, connect | security_compliance | — | connect, security_compliance ✓ | security_compliance, connect ✓ |
| mm-net30-and-campaign-report | multi_intent_multi_turn | test | billing, data | billing, data ✓ | billing, data ✓ | billing, data ✓ | billing, data ✓ |
| mm-bike-shop-counters | multi_intent_multi_turn | test | terminal, fraud_protection (+ payments) | payments, terminal, fraud_protection ✓ | — | payments, terminal, fraud_protection ✓ | terminal |
| mm-soc2-and-three-year-discount | multi_intent_multi_turn | test | security_compliance, pricing_conversation | — | — | security_compliance, pricing_conversation ✓ | security_compliance, pricing_conversation ✓ |
