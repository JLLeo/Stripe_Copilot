# Stripe Link

Product Line: Payment
Product: Link
Topic: Digital Wallet / Accelerated Checkout
Source Type: public_doc
Access Level: public
Sales Scenario: faster_checkout / conversion_optimization / payment_method_save
Last Updated: 2026-07-16
Source URL: https://docs.stripe.com/payments/link

## Summary

Stripe Link is Stripe's digital wallet that securely saves and autofills customer payment details and shipping addresses across sites. Customers authenticate once via a one-time passcode sent to their email or phone, and Link then autofills their saved payment methods for frictionless checkout on any Stripe merchant. Link supports cards, US bank accounts, and BNPL options including Klarna, with exclusive access to lower-cost Instant Bank Payments.

## Key Capabilities

- **Faster checkout**: Autofills payment details and shipping addresses — reduces checkout friction and cart abandonment
- **Cross-merchant recognition**: Link detects enrolled customers by email, phone number, or browser cookie across any Stripe-powered site
- **One-time passcode authentication**: Simple, secure authentication without passwords
- **Instant Bank Payments**: Link-exclusive lower-cost payment method — reduces processing costs vs. cards
- **Instant confirmation**: All transactions confirmed immediately regardless of funding method
- **Same settlement timeline**: Settles to Stripe balance on the same timeline as card payments
- **Multi-payment-method wallet**: Supports cards, US bank accounts, and BNPL (Klarna on Link — public preview)
- **Self-service customer portal**: Customers manage accounts, view purchase history, and get support at link.com
- **Works everywhere**: Compatible with Checkout (no-code), Payment Links, Invoicing, Payment Element, Express Checkout Element, Mobile Payment Element, and custom Payment Intents integrations
- **Multiple backup payment methods**: Customers can add backup cards in case primary method fails
- **Country restrictions**: Not available in India; Payment Element does not support Link in Brazil and Thailand

## Sales Use Case

Use this document when a customer asks about improving checkout conversion, reducing cart abandonment, enabling faster repeat purchases, lowering payment processing costs (via bank payments), or offering a digital wallet experience without building one themselves.

## Client-ready Explanation

Stripe Link is a digital wallet that makes checkout dramatically faster for returning customers. Once a customer uses Link anywhere on the Stripe network, their payment details are securely saved — on their next purchase at any Stripe merchant, they just verify with a one-time code and all their info autofills. For businesses, Link means higher conversion rates and lower cart abandonment. Plus, Link customers can pay via Instant Bank Payments — a lower-cost alternative to cards that's exclusive to Link — saving you money on processing fees.

## Key Discovery Questions

- What is the customer's checkout conversion rate, and are they trying to improve it?
- Do they have many repeat customers or primarily one-time buyers?
- What is their current cart abandonment rate?
- Are they looking to reduce payment processing costs? (Instant Bank Payments can help)
- Which Stripe integration are they using (Checkout, Elements, Payment Links, Invoicing)?
- Do they operate in India, Brazil, or Thailand? (Link availability varies)
- Do their customers prefer paying by bank transfer vs. credit card?
- Would they benefit from customers having Link autofill shipping addresses as well?

## Price

- Link with domestic cards: 2.9% + $0.30 (same as standard card rate)
- Link with Instant Bank Payments: 2.6% + $0.30 (lower cost than cards)
- No additional monthly fees or setup costs for Link
- Included automatically when you enable card and bank payment methods in Dashboard

## Escalation Notes

- If the customer wants co-branded wallet experiences or custom Link branding, escalate to product team
- For enterprise merchants seeking data on Link's conversion impact specific to their vertical, escalate to analytics team
- If the customer operates in a region where Link is not yet available, escalate to product team for roadmap information
- For questions about Link's fraud/chargeback liability model, escalate to risk team
