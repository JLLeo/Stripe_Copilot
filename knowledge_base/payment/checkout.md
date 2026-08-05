# Stripe Checkout

Product Line: Payment
Product: Checkout
Topic: Prebuilt Payment UI
Source Type: public_doc
Access Level: public
Sales Scenario: ecommerce_checkout / low_code_payment_page
Last Updated: 2026-07-16
Source URL: https://docs.stripe.com/payments/checkout

## Summary

Stripe Checkout is a prebuilt, Stripe-hosted payment page that helps businesses accept online payments with minimal engineering effort. It supports one-time payments, subscriptions, 125+ local payment methods, billing, tax calculation, adaptive pricing, promo codes, and upsells — all out of the box.

## Key Capabilities

- **Full-featured payment page**: Prebuilt UI with order summary (subtotals, tax, shipping), cross-sells/upsells, free trials, discounts, and promo codes
- **Three deployment modes**: Hosted page (redirect to Stripe), Embedded form (stays on your site, private preview), or custom Elements-based page
- **One-time payments & subscriptions**: Supports both payment types natively
- **125+ payment methods**: Cards, wallets (Apple Pay, Google Pay), bank debits (ACH, SEPA), BNPL (Klarna, Afterpay), and more — dynamically displayed based on customer locale
- **Adaptive Pricing**: Automatically shows prices in the customer's local currency to increase conversion
- **Managed Payments**: Stripe handles sales tax/VAT compliance in 80+ countries as merchant of record
- **Low maintenance**: Stripe handles updates, payment method additions, and compliance automatically
- **Customization**: 15 configurable settings via brand settings (Full Page), 70 configurable settings via Appearance API (Embedded Form), or full CSS control (Elements mode)
- **Checkout Studio** (private preview): Configure, monitor performance, and run experiments on your checkout

## Sales Use Case

Use this document when a customer asks about launching a payment page quickly, improving checkout conversion, reducing engineering work for payment integration, or wanting a solution that stays up to date with the latest payment methods automatically.

## Client-ready Explanation

Stripe Checkout is ideal if you want a fully-featured, conversion-optimized payment page without having to build and maintain it yourself. It supports one-time and recurring payments, shows customers their local currency and preferred payment methods automatically, and handles tax compliance. Our early users saw up to a 46% increase in sales after enabling local payment methods through Checkout.

## Key Discovery Questions

- Does the customer need one-time payments, subscriptions, or both?
- Do they prefer a hosted checkout page (customer redirects to Stripe) or embedded checkout (stays on their site)?
- How much UI customization do they need (brand colors vs. full CSS control)?
- Do they need support for specific local payment methods (e.g., iDEAL, Alipay, SEPA)?
- Do they need tax/VAT compliance across multiple countries?
- Do they want to offer promo codes, upsells, or cross-sells at checkout?
- Do they need to save customer payment methods for future purchases?

## Price

Checkout itself is included at no extra charge with standard Stripe Payments processing. Additional feature pricing:
- Custom domain: $10.00/month
- Post-payment invoices: 0.4% on transaction total ($2.00 cap per invoice)
- Standard payment processing: 2.9% + $0.30 per successful domestic card charge

## Escalation Notes

- If the customer asks about custom pricing, complex compliance requirements, or guaranteed conversion lift, escalate to the appropriate internal team
- For customers needing highly customized checkout flows beyond the Appearance API, suggest evaluating Elements
- If the customer operates in a high-risk industry or needs specialized fraud settings, involve the Radar team
- For enterprise customers requiring dedicated onboarding support, escalate to enterprise sales
