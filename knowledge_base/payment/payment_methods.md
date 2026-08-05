# Stripe Payment Methods

Product Line: Payment
Product: Payment Methods
Topic: Payment Method Acceptance
Source Type: public_doc
Access Level: public
Sales Scenario: payment_method_selection / global_payments
Last Updated: 2026-07-16
Source URL: https://docs.stripe.com/payments/payment-methods

## Summary

Stripe supports 100+ payment methods across multiple categories, enabling businesses to accept payments from customers worldwide. The Payment Methods API provides a unified interface for managing different payment types, with Stripe automatically handling method-specific requirements, compliance notices, and localized form rendering. Dynamic payment methods automatically display the most relevant options for each customer based on location, currency, and transaction context.

## Key Capabilities

- **Cards**: Visa, Mastercard, American Express, Discover, JCB, UnionPay, and more
- **Wallets**: Apple Pay, Google Pay, PayPal, WeChat Pay, Alipay, GrabPay
- **Bank debits**: ACH Direct Debit (US), SEPA Direct Debit (EU), Bacs Direct Debit (UK), Pre-authorized debits (Canada)
- **Bank redirects**: Bancontact, EPS, FPX, Giropay, iDEAL, Przelewy24, Sofort
- **Buy Now, Pay Later (BNPL)**: Klarna, Affirm, Afterpay/Clearpay
- **Vouchers**: OXXO (Mexico), Boleto (Brazil)
- **Crypto**: Stablecoins via Stripe-hosted onramp
- **Link**: Stripe's digital wallet for faster checkout with saved payment details
- **Dynamic payment methods**: Automatically orders and displays methods most likely to convert — no code changes needed when new methods are added
- **Unified API**: Single Payment Methods API across all payment method types
- **Reusable payment methods**: Cards and bank debits can be saved for future use
- **Automatic compliance**: Stripe handles local mandates, consent notices, and regulatory requirements per method
- **Localized forms**: Payment forms auto-localize based on customer location

## Sales Use Case

Use this document when a customer asks about which payment methods to support, needs to expand into new geographic markets, wants to understand payment method coverage in specific countries, or is evaluating whether Stripe supports their customers' preferred payment methods.

## Client-ready Explanation

Stripe supports over 100 payment methods globally, from credit cards to digital wallets to bank transfers to buy-now-pay-later. The key advantage is that Stripe's dynamic payment methods feature automatically shows each customer the payment options most likely to convert — based on where they are, what currency they use, and what device they're on. You enable methods once in the Dashboard, and Stripe handles the rest, including all the local compliance requirements. No need to integrate each method individually.

## Key Discovery Questions

- What countries/regions do the customer's end users come from?
- Which payment methods are most important for their specific market (e.g., iDEAL in Netherlands, Alipay in China, Boleto in Brazil)?
- Do they need to save payment methods for recurring billing?
- What is their current payment method conversion rate and are they looking to improve it?
- Do they have a preference for cards vs. alternative payment methods?
- Are they interested in BNPL options for their customers?
- Do they want to accept crypto/stablecoins?

## Price

Payment method pricing varies by method type:
- Domestic cards: 2.9% + $0.30
- ACH Direct Debit: 0.8% (capped at $5.00)
- Klarna/BNPL: 5.99% + $0.30
- Stablecoins: 1.5% of transaction
- International cards: +1.5% surcharge
- Link Instant Bank Payments: 2.6% + $0.30

No additional monthly fees for enabling payment methods. See [stripe.com/pricing](https://stripe.com/pricing) for complete details per method.

## Escalation Notes

- If a customer requests a payment method not currently supported by Stripe, escalate to product team with specific market requirements
- For enterprise customers needing custom payment method pricing, escalate to Stripe sales
- If the customer operates in a high-value industry with unique payment method compliance needs, involve compliance specialists
- For complex multi-country payment method rollouts, consider involving Stripe professional services
