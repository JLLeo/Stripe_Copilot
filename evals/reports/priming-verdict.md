# The Priming verdict

3 runs of the nineteen behaviour cases with Priming off and 2 with it on, at threshold 0.55, margin 0.2, Decider jev-latest — the defaults #18 fitted. **Priming kept quality and took tool rounds away; whether that made turns faster is inside the runs' own variation.**

## 1. Quality must not degrade

| | Priming off | Priming on |
|---|---|---|
| First-action accuracy | 98% | 100% |
| Judge mean | 4.26 | 4.38 |
| Leaks | 0 | 0 |
| Runs with errored cases | 0 | 0 |

Every run with Priming on is within the noise of the runs with it off (5% of first-action accuracy, 0.24 of the judge's mean) and nothing leaked: quality held.

First-action accuracy is not measured quite the same way on both sides: with Priming on, a primed skill counts as the first move. Of the 38 passes with Priming on, 27 rest on that credit — the model's own first response would not have matched. So that row mostly says whether the right skill got in first; the judge says what the model then did with it.

## 2. The committed claims, turn by turn

| Claim (#14) | Measured | Held |
|---|---|---|
| On a primed turn the first response does not reload a primed skill | 0 of 38 primed turns did; 0 loaded a skill Priming missed, the fallback | ✓ |
| Tool rounds drop by one where a skill-only round existed | mean drop 1.2 over 13 such turns; 10 dropped a full round | ✓ |
| The Decider spends ≤ 0.7 s at p95 | p95 0.3 s, p50 0.2 s, max 0.3 s over 50 asks | ✓ |
| No turn is slower with Priming on | 9 of 25 turns slower by median; 2 slower in every run, where chance alone gives 2.5 (as many or more by chance: p = 0.71) | ✓ |

The rounds claim holds on average: a turn's rounds also move with what the model decides to look up, so some turns keep a round for other reasons. The last claim is a weak test with 2 runs with Priming on and 3 off: chance alone produces 2.5 turns slower in every run, so only a slowdown on many turns would show.

Turns slower in every run with Priming on:

| Case | Turn | Off (ms) | On (ms) | Decider (ms) | Rounds off | Rounds on | Primed | Fewer rounds, yet slower |
|---|---|---|---|---|---|---|---|---|
| fraud_chargebacks | 1 | 10137, 10945, 13906 | 15155, 24642 | 255, 211 | 2, 3, 2 | 1, 2 | fraud_protection; fraud_protection | yes |
| tax_cross_border | 2 | 15000, 16100, 19325 | 20517, 21019 | 198, 199 | 1, 2, 1 | 1, 3 | —; — | no |

A turn with fewer rounds that is still slower spent its time elsewhere — in reasoning or in the reply — which these metrics do not separate; the Decider's own time there is in the table.

## 3. Speed and rounds

Each turn with Priming on minus the same turn with it off, averaged over turns. The interval resamples the runs of each mode as well as the turns, because whole runs differ from one another.

| | Change per turn | |
|---|---|---|
| Turn latency | -1.6 s (95% -4.1 to +0.9) | not established |
| Tool rounds | -0.64 (95% -0.97 to -0.29) | fewer |
| Latency where a skill-only round existed and Priming primed | -1.2 s (95% -4.3 to +2.2) | |
| Latency on the other turns | -2.0 s (95% -5.7 to +0.8) | |

Mean turn latency per run: with Priming off 13.0 s, 14.8 s, 15.8 s; with it on 13.1 s, 12.8 s. At that run-to-run spread, about 5 runs a side would separate a change of the size measured.

| | Priming off | Priming on |
|---|---|---|
| Turn latency p50 / p90 | 13.5 s / 25.8 s | 11.4 s / 24.3 s |
| Case latency p50 / p90 (#14's baseline: 13.7 s / 48.8 s) | 15.7 s / 37.6 s | 12.1 s / 36.7 s |
| First turns pairing `Skill` with a tool it informs, per run (#14: 6 of 19) | 3, 2, 5 | 0, 0 |
| Turns primed | — | 38 of 50 (76%) |
| Primed turns asking again for a skill already in context | — | 0 (0%) |

Why the other turns were not primed: below_threshold 12.

#14 expected p90 to improve while p50 stayed near where it was. The runs with Priming off disagree by 3.2 s at turn p50 and 10.1 s at turn p90, so pooled percentiles cannot confirm or refute that expectation; the paired change above is the measure, and it is not yet separated from zero. #14 also reasoned that removing a round saves that round's time; here the turns that lost a skill-only round saved no more than the other turns did, so these runs cannot tie a latency change to the round that went.

The first-turn pairing with Priming off ran 3, 2, 5 of 19 in these runs against #14's 6, so part of that drop had happened before Priming; with Priming on it is 0, 0.

## 4. Recommendations

Skill selection on the Golden Set (#17, development and held-out averaged):

| Arm | Skill F1 | Skill recall | Decision p50 | Tool recall |
|---|---|---|---|---|
| main-thinking | 93% | 88% | 2.9 s | 66% |
| main-no-thinking | 68% | 52% | 1.9 s | 31% |
| sub-model | 96% | 95% | 2.0 s | 69% |
| decider | 84% | 78% | 0.2 s | — |

**Recommendation:** Priming can be turned on (`HARNESS_PRIMING=1`): it kept quality and took tool rounds away. Its effect on latency is not yet separated from the provider's run-to-run drift; about 5 runs a side would show a change of the size measured.

**The next lever is `sub-model`:** it chooses skills within the Golden Set's noise of the main model with thinking on and decides faster. At 1.7 model calls a turn and 0.9 s saved per decision, that is roughly 1.5 s a turn, a turn p50 near 9.8 s — short of the 6 s #14 aimed at, on its own. Turning thinking off is not the lever: it loses 25 points of skill F1. Evaluate it as the main model on the behaviour cases and the Golden Set, with the judge watching what it says as well as what it calls; adopting it is a separate decision.
