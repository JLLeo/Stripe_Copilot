---
name: connect
description: Platforms and marketplaces — Connect for collecting from buyers, paying out sellers, onboarding connected accounts, platform fees. Load when the customer serves parties who get paid.
---

# Connect — platforms and marketplaces

Stripe Connect is for businesses that move money between parties: a
marketplace paying sellers, a SaaS platform letting its merchants accept
payments, an on-demand app paying drivers, a crowdfunding site paying creators.
If the customer only takes payments for themselves, they do not need Connect —
say so and steer to `payments`.

## Which model fits

| Model | Money flow | Examples |
|---|---|---|
| **SaaS platform** | Each business accepts payments from its own customers; the platform may take a fee | Shopify, Squarespace |
| **Marketplace** | Platform collects from buyers, splits fees, pays out to sellers or providers | Uber, Airbnb, Fiverr |
| **Payouts platform** | Platform mainly sends money out to recipients worldwide | creator economy, gig work |

## Onboarding connected accounts

Standard, Express and Custom onboarding differ in how much of the experience
the platform owns; KYC/KYB verification is built into all three. Connect
embedded components put onboarding, payments and payouts UI directly inside
the platform's own product. Account capabilities (card payments, transfers,
payouts) are granted per account.

## Money movement and control

- Split a charge between platform fee and seller payout; direct, destination
  and separate charges-and-transfers cover the common flows.
- Payout schedules (daily, weekly, monthly, manual), external bank accounts,
  international payouts.
- Platform pricing tool: set the processing fee connected accounts pay
  (markups from 0.25%).
- Radar protects connected-account transactions; Stripe Tax calculates tax on
  behalf of connected accounts; Revenue Recognition understands platform fees
  and pass-through amounts.

## What to establish before recommending

- Who gets paid, and does the platform want to take a cut?
- Who should own the seller's onboarding experience and support burden?
- Countries of sellers and buyers; payout currencies.
- Does the platform want to set its own processing fees for sellers?
- Existing Stripe products in the profile — a business model of "Marketplace" or "Platform" points here.

## Pricing

Connect pricing depends on the account type and money flow, on top of standard
processing; platform buy-rates and custom terms exist for larger platforms but
are arranged by Stripe's sales team. Use `get_pricing` for what is public and
be explicit about what is not.

## When to bring in a human

Cross-border payout design, complex multi-party flows, custom onboarding
requirements, regulatory questions about who is the merchant of record, or
platform pricing. Offer to connect them with a solutions engineer.
