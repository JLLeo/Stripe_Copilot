---
name: billing
description: Recurring revenue — Billing, Subscriptions, Invoicing, Revenue Recognition. Load for SaaS pricing models, subscriptions, trials, dunning, invoices, quotes, or ASC 606 / IFRS 15 reporting.
---

# Billing and recurring revenue

Stripe Billing runs the subscription lifecycle end to end: pricing models,
trials, proration, renewals, retries, invoices and the customer-facing portal.
Invoicing and Revenue Recognition sit alongside it.

## Products in this area

- **Billing / Subscriptions** — create, update, pause, cancel and reactivate
  subscriptions; flat-rate, per-seat, usage-based (metered), tiered
  (graduated or volume), and multi-currency pricing; trials with automatic
  conversion; proration on mid-cycle changes; subscription schedules for
  pre-planned changes; Smart Retries (ML-timed retries that recover failed
  payments); coupons and promo codes; webhooks for every lifecycle event.
- **No-code pieces** — an embeddable **Pricing Table** that sends customers
  into Checkout, and a hosted **Customer Portal** where customers change plans,
  update cards and view invoices without support tickets.
- **Quotes** — price estimates the customer accepts before the subscription or
  invoice starts.
- **Invoicing** — one-off and recurring invoices from the Dashboard or API;
  hosted invoice page with 40+ payment methods; auto-charge of a saved method;
  Smart Retries and dunning emails; partial payments and payment plans; credit
  notes; automatic reconciliation of bank transfers; per-customer currency.
- **Revenue Recognition** — accrual accounting on top of Stripe data; ASC 606
  and IFRS 15 rules out of the box, custom rules, chart-of-accounts mapping,
  audit trail from report to transaction, Connect-aware.

## What to establish before recommending

- What is the pricing model today, and where is it going (seats, usage, tiers)?
- Do they invoice businesses (net terms, PO numbers) or charge cards automatically?
- How much involuntary churn from failed payments do they see?
- Do they need finance-grade reporting (close, audits, ASC 606)?
- Are they on Stripe Payments already? Billing works with any Stripe payment surface.

Pull the customer's profile: a SaaS or subscription business model, or existing
Payments usage without Billing, is the natural opening.

## Pricing

Billing pay-as-you-go: 0.7% of Billing volume (on- and off-Stripe); a monthly
plan starts at $620/month on a one-year contract. Invoicing Starter: 0.4% per
paid invoice. Revenue Recognition: $25/month, or from $190/month billed
annually for the larger tier. Standard processing fees apply to the payments
themselves. Confirm with `get_pricing`; never quote a discount.

## Talking points

- Smart Retries and the Customer Portal pay for themselves in recovered revenue and fewer tickets.
- Usage-based and hybrid models are first-class, not a workaround.
- Invoicing and Subscriptions share one customer object, one tax engine (load `tax`), one Dashboard.

## When to bring in a human

Enterprise contract terms, monthly-plan pricing, migrations from another
billing system with complex data, or accounting questions that need a
finance specialist.
