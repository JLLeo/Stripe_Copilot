---
name: payments
description: Accepting online payments — Checkout, Elements, Payment Links, Link, payment methods, global reach. Load for "how do we take payments", checkout UX, conversion, or payment-method coverage.
---

# Payments

Stripe Payments is the core: accept payments online and in person, in 135+
currencies with local acquiring in 46+ countries, through whichever integration
surface fits the customer's engineering appetite.

## The surfaces, and who each is for

| Surface | What it is | Recommend when |
|---|---|---|
| **Payment Links** | A shareable link or buy button created in the Dashboard; no code | No developers, selling a few products, donations, invoices-by-link, social/SMS selling |
| **Checkout** | A Stripe-hosted (or embedded) prebuilt payment page; one-time and subscriptions; 125+ methods; Adaptive Pricing | Wants a conversion-optimised page fast with minimal maintenance; small team or early stage |
| **Elements** | Prebuilt, PCI-compliant UI components (Payment, Express Checkout, Address, Link…) styled with the Appearance API | Has a dev team and wants full brand control while Stripe keeps card data off their servers |
| **Link** | Stripe's wallet: saved payment details across the Stripe network, one-time passcode login; Instant Bank Payments at 2.6% + $0.30 | Returning-customer conversion; comes free with Checkout, Elements and Payment Links |

Rule of thumb: Payment Links → Checkout → Elements is the ladder of increasing
control and engineering effort. Do not recommend Elements to a team with no
developers; do not recommend Payment Links to a business with a custom cart.

## Payment methods

100+ methods behind one API: cards (Visa, Mastercard, Amex, Discover, JCB,
UnionPay), wallets (Apple Pay, Google Pay, PayPal, WeChat Pay, Alipay), bank
debits (ACH, SEPA, Bacs, Canadian PADs), bank redirects (iDEAL, Bancontact,
Giropay, Przelewy24…), BNPL (Klarna, Affirm, Afterpay/Clearpay), vouchers
(OXXO, Boleto), stablecoins, and Link. **Dynamic payment methods** shows each
customer the methods most likely to convert for their location — no code
change when Stripe adds a method. Stripe handles local mandates and consent.

## What to establish before recommending

- Do they have developers, and how much do they want to own the checkout UI?
- One-time payments, subscriptions, or both? (Subscriptions → also load `billing`.)
- Where are their customers? Which currencies and local methods matter?
- Selling in person too? (Load `terminal`.)
- A platform or marketplace paying out to others? (Load `connect`.)
- Fraud or dispute concerns? (Load `fraud_protection`.)

Check the customer's profile first: their integration maturity, business
model and current products decide which surface to lead with.

## Pricing

Standard: 2.9% + $0.30 per successful domestic card charge; +1.5% international
cards; +1% currency conversion; ACH 0.8% capped at $5; Link Instant Bank
Payments 2.6% + $0.30; BNPL 5.99% + $0.30. Checkout, Elements, Payment Links
and Link add no fee of their own (custom domain for Checkout is $10/month).
Always confirm with `get_pricing` before quoting; never quote custom rates.

## Talking points customers respond to

- "You only pay when you get paid" — no setup or monthly fees on standard pricing.
- Adaptive Pricing shows local currency automatically and lifts conversion.
- Stripe maintains compliance, payment-method additions and updates for you.

## When to bring in a human

Custom pricing or interchange-plus requests, very high volumes, complex
multi-entity setups, or contract terms. Say so plainly and offer to connect them.
