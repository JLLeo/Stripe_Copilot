---
name: tax
description: Stripe Tax — automatic sales tax, VAT and GST calculation, registration threshold monitoring, filing. Load for any tax, VAT, GST, nexus, or "do we need to register" question.
---

# Tax

Stripe Tax calculates and collects the right sales tax, VAT or GST on every
transaction, watches registration thresholds, and — on Tax Complete — files the
returns. It works across Checkout, Payment Links, Invoicing, Subscriptions,
custom Payment Intents integrations, off-Stripe transactions, and Connect
platforms calculating on behalf of connected accounts.

## What it does

- **Calculation** from product tax codes (SaaS vs physical goods vs digital
  services) plus customer location and the business's registrations; US sales
  tax, EU and UK VAT, AU/NZ GST and more.
- **Threshold monitoring** — tracks cumulative sales per jurisdiction and
  alerts when a registration is required.
- **Registration management** — manage registrations globally; Stripe can
  register for sales tax on the business's behalf.
- **Filing** (Tax Complete) — return preparation and filing with authorities.
- **Reporting** for filing and audits.

## The line you must hold

Explain what Stripe Tax does and how it would apply to the customer's products
and markets. Do **not** tell a customer whether they are liable, where they
must register, or how to treat a specific transaction — that is tax advice.
When the question becomes "what should we do about our obligations", offer a
tax specialist.

## What to establish before recommending

- Which countries and states do they sell into, and what do they sell (digital, physical, services)?
- Are they registered anywhere today? Handling filing themselves or with an accountant?
- Which Stripe surfaces do they use? Tax attaches to all of them.
- Marketplace or platform? (Connect-aware calculation — load `connect`.)

## Pricing

Tax Complete from $90/month on a one-year contract (monitoring, registrations,
calculation and filing). Tax Basic: 0.5% per transaction where registered
(no-code), or $0.50 per transaction via API including 10 calculation calls
($0.05 per additional call). Confirm with `get_pricing`.

## Talking points

- One tax engine across every way they get paid, including invoices and subscriptions.
- Threshold alerts remove the "we didn't know we crossed nexus" surprise.
- Filing can be taken off their plate entirely.

## When to bring in a human

Liability, registration strategy, back taxes, audits, or anything that asks
for a decision about their obligations rather than a description of the product.
