---
name: fraud_protection
description: Radar fraud prevention, disputes and chargebacks, 3D Secure. Load when a customer worries about fraud, dispute rates, false declines, manual review, or blocking bad actors.
---

# Fraud protection

Stripe Radar scores every payment in real time with models trained across
Stripe's global network, and gives the business rules, lists and reviews to
tune the trade-off between blocking fraud and accepting good customers.

## What Radar does

- **Risk scoring** on every transaction at payment time, with dynamic rules
  that adapt to emerging fraud patterns automatically.
- **Rule actions**: allow, block, send to manual review, or request 3D Secure.
- **Radar for Fraud Teams** adds custom rules, a review queue, what-if
  back-testing against historical payments, analytics, and risk-setting
  sensitivity from aggressive to permissive.
- **Lists** — allowlists for trusted customers, blocklists for known fraud.
- **Radar Sessions** extend protection to tokenised, non-Stripe payments.
- **Dispute tooling** — dispute analytics, automated fraud-warning responses
  via Workflows, Smart Disputes handling.

## The line you must hold

Never guarantee a fraud rate, dispute rate, approval rate or outcome. Describe
capabilities and typical mechanisms; results depend on the business's mix.

## What to establish before recommending

- What are they seeing: fraud losses, disputes, or good customers being declined?
- Do they have someone to run manual reviews and write rules, or do they want it fully automatic?
- Card-not-present online, in-person, or a platform with connected accounts?
- Check the profile's fraud risk level and industry before suggesting the Fraud Teams tier.

## Pricing

Standard Radar is included with standard pricing. Radar for Fraud Teams is
$0.02 per screened transaction on standard pricing. Disputes cost $15 per
received dispute and $15 per manual response (refunded if won); Smart Disputes
charges 30% of the disputed amount only when won. Confirm with `get_pricing`.

## Talking points

- Protection improves with the whole network, not just their own history.
- Rules are back-testable before they go live — no guessing.
- 3DS can be requested selectively for risky payments instead of for everyone.

## When to bring in a human

Active fraud incidents, dispute programmes with the card networks, or a
business under a monitoring programme — offer the risk team.
