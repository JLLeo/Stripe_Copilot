---
name: terminal
description: In-person payments with Terminal — card readers, Tap to Pay, POS integrations, unified online and in-store reporting. Load for retail, restaurants, events, or paying in person.
---

# Terminal — in-person payments

Stripe Terminal brings in-person payments into the same account, Dashboard and
customer objects as online payments, so a business sees one view of a customer
who buys in store and online.

## Integration paths

| Path | For |
|---|---|
| **Standalone mode** (no code) | Take payments on a reader with no integration |
| **Tap to Pay** on iPhone or Android | Mobile sellers, pop-ups, field sales — no hardware |
| **SDKs** (JavaScript, iOS, Android, React Native) | A custom point of sale |
| **Apps on smart readers** | Deploy an Android POS app directly to the reader |
| **Third-party POS** | Existing POS systems that integrate Stripe |

## Hardware

Reader M2 ($59) for mobile and light use; Reader S710 ($299) and S700 ($299)
smart readers with screens for line items, totals and tipping. Offline mode
keeps taking payments through poor connectivity.

## Capabilities that matter in sales conversations

Contactless and wallets (Apple Pay, Google Pay); save a card at the point of
sale to start a subscription or attach to a customer; dynamic reader displays;
compliant digital receipts; tip adjustments; Connect support for platforms
selling in person; PCI PA-DSS and EMVCo Level 1 and 2 certification.

## What to establish before recommending

- Fixed counters, mobile staff, or both? Number of locations?
- Existing POS software they want to keep, or building their own?
- Do they already sell online with Stripe? Unified reporting is the strongest reason to consolidate.
- Connectivity conditions (events, venues) → offline mode.

## Pricing

Domestic card-present 2.7% + $0.05 per transaction; +1.5% international;
Tap to Pay +$0.10 per authorisation; optional P2PE encryption +$0.05 per
authorisation; hardware as above. Confirm with `get_pricing`.

## When to bring in a human

Large hardware roll-outs, custom reader apps, or multi-country in-person
deployments — offer a solutions engineer.
