# Golden Set report

Run: 2026-10-03 03:27 UTC · covers the held-out split (test), 40 cases

Arms: `decider` = jev-latest at threshold 0.55, margin 0.2, timeout 0.7 s.

Skill selection is the `Skill` calls of a model arm's first response, or the skills the Decider primed. Precision and recall are micro-averaged; a choice among a case's acceptable skills costs nothing. Latency is to the skill decision.

## Skill selection

| Arm | Cell | Cases | Exact | Precision | Recall | F1 | First action | p50 ms | p90 ms | Errors |
|---|---|---|---|---|---|---|---|---|---|---|
| decider | all | 40 | 80% | 93% | 91% | 92% | 98% | 156 | 194 | 0 |
| decider | single_intent_single_turn | 10 | 70% | 86% | 89% | 87% | 90% | 145 | 174 | 0 |
| decider | multi_intent_single_turn | 10 | 70% | 100% | 86% | 93% | 100% | 176 | 232 | 0 |
| decider | single_intent_multi_turn | 10 | 90% | 86% | 100% | 92% | 100% | 149 | 156 | 0 |
| decider | multi_intent_multi_turn | 10 | 90% | 95% | 95% | 95% | 100% | 162 | 193 | 0 |

## Tool selection (model arms)

The tools a model arm calls with the instructions in hand: its first response's tools when it called one a skill informs — *paired* counts those that also loaded a skill, so chose a tool before reading its instructions — otherwise the next response, once those calls are answered. Tools no skill informs (profile, catalogue, remember) are not scored. Latency is to that decision.

| Arm | Cell | Exact | Precision | Recall | F1 | Paired | p50 ms | p90 ms |
|---|---|---|---|---|---|---|---|---|

## Decisions by case

Each arm's skills, ✓ when the set is exact. The Decider shows why it primed nothing.

| Case | Cell | Split | Required skills (+ acceptable) | decider |
|---|---|---|---|---|
| ss-prospect-card-fee-first | single_intent_single_turn | test | discovery (+ pricing_conversation) | pricing_conversation |
| ss-prospect-45m-call | single_intent_single_turn | test | discovery | discovery, payments |
| ss-person-video-call | single_intent_single_turn | test | — | — (below_threshold) ✓ |
| ss-prepaid-credits-january | single_intent_single_turn | test | billing | billing ✓ |
| ss-month-end-netsuite | single_intent_single_turn | test | data (+ billing) | data ✓ |
| ss-good-buyers-blocked | single_intent_single_turn | test | fraud_protection (+ payments) | fraud_protection, payments ✓ |
| ss-tap-to-pay-fee | single_intent_single_turn | test | pricing_conversation (+ terminal) | pricing_conversation, terminal ✓ |
| ss-dutch-belgian-methods | single_intent_single_turn | test | payments | payments ✓ |
| ss-elements-pci-scope | single_intent_single_turn | test | security_compliance (+ payments) | security_compliance, payments ✓ |
| ss-singapore-stores-zh | single_intent_single_turn | test | terminal | terminal, payments |
| ms-prospect-tutoring-es | multi_intent_single_turn | test | discovery, connect (+ pricing_conversation) | connect, pricing_conversation |
| ms-prospect-hr-soc2-invoices | multi_intent_single_turn | test | discovery, security_compliance, billing | security_compliance, billing |
| ms-eu-vat-euro-plans | multi_intent_single_turn | test | tax, billing (+ payments) | tax, billing ✓ |
| ms-dashboard-queries-proration | multi_intent_single_turn | test | data, billing | billing, data ✓ |
| ms-market-stall-qr-orders | multi_intent_single_turn | test | terminal, payments | terminal, payments ✓ |
| ms-fake-sellers-stolen-cards | multi_intent_single_turn | test | connect, fraud_protection | fraud_protection, connect ✓ |
| ms-checkout-pci-sales-tax | multi_intent_single_turn | test | security_compliance, tax (+ payments) | security_compliance, tax ✓ |
| ms-card-testing-fraud-teams | multi_intent_single_turn | test | fraud_protection, pricing_conversation | fraud_protection, pricing_conversation ✓ |
| ms-course-platform-ramble | multi_intent_single_turn | test | connect, tax, billing | connect, tax |
| ms-too-technical-currencies | multi_intent_single_turn | test | objection_handling, payments | payments, objection_handling ✓ |
| sm-applepay-on-top | single_intent_multi_turn | test | pricing_conversation | pricing_conversation ✓ |
| sm-donors-monthly-gift | single_intent_multi_turn | test | billing | billing ✓ |
| sm-branded-checkout-no-code | single_intent_multi_turn | test | payments | payments ✓ |
| sm-patient-invoices-hipaa | single_intent_multi_turn | test | security_compliance | security_compliance ✓ |
| sm-dunning-tool-rant | single_intent_multi_turn | test | objection_handling | objection_handling ✓ |
| sm-es-tarjetas-robadas | single_intent_multi_turn | test | fraud_protection | fraud_protection, security_compliance |
| sm-pause-ends | single_intent_multi_turn | test | — | — (below_threshold) ✓ |
| sm-caregiver-verification-time | single_intent_multi_turn | test | — | — (below_threshold) ✓ |
| sm-candles-monthly-cost | single_intent_multi_turn | test | — | — (below_threshold) ✓ |
| sm-offtopic-product-names | single_intent_multi_turn | test | — | — (below_threshold) ✓ |
| mm-zh-disputes-and-front-desk | multi_intent_multi_turn | test | fraud_protection, terminal | fraud_protection, terminal ✓ |
| mm-fraud-vendor-and-disputes | multi_intent_multi_turn | test | objection_handling, fraud_protection | fraud_protection, objection_handling ✓ |
| mm-eu-tax-cost-and-registration | multi_intent_multi_turn | test | pricing_conversation, tax | tax, pricing_conversation ✓ |
| mm-warehouse-counters-sales-tax | multi_intent_multi_turn | test | terminal, tax | tax, terminal ✓ |
| mm-onsite-cut-and-bank-transfer | multi_intent_multi_turn | test | connect, payments | connect, pricing_conversation |
| mm-bank-terminals-objection | multi_intent_multi_turn | test | objection_handling, terminal | objection_handling, terminal ✓ |
| mm-au-residency-new-countries | multi_intent_multi_turn | test | security_compliance, connect | security_compliance, connect ✓ |
| mm-net30-and-campaign-report | multi_intent_multi_turn | test | billing, data | billing, data ✓ |
| mm-bike-shop-counters | multi_intent_multi_turn | test | terminal, fraud_protection (+ payments) | terminal, fraud_protection ✓ |
| mm-soc2-and-three-year-discount | multi_intent_multi_turn | test | security_compliance, pricing_conversation | security_compliance, pricing_conversation ✓ |
