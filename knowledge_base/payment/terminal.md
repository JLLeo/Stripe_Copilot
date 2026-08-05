# Stripe Terminal

Product Line: Payment
Product: Terminal
Topic: In-person Payments
Source Type: public_doc
Access Level: public
Sales Scenario: point_of_sale / in_person_payments / unified_commerce
Last Updated: 2026-07-16
Source URL: https://docs.stripe.com/terminal

## Summary

Stripe Terminal enables businesses to accept in-person payments while managing both online and in-person transactions in a unified Stripe Dashboard. It offers SDKs for custom POS integrations, no-code options via Tap to Pay and Standalone Mode, and a range of card readers. Terminal supports debit/credit cards, contactless payments, and mobile wallets with features like offline mode, tip adjustments, and digital receipts.

## Key Capabilities

- **In-person payment acceptance**: Debit/credit cards, contactless payments, and mobile wallets (Apple Pay, Google Pay)
- **Unified Dashboard**: Manage online and in-person payments in one place
- **Multiple integration paths**: Custom POS via SDKs (JavaScript, iOS, Android, React Native), Tap to Pay on compatible phones, Standalone Mode (no-code), apps on smart readers, third-party POS via gateway
- **Card readers**: Reader M2 ($59), Reader S710 ($299), Reader S700 ($299) — designed for different business sizes and needs
- **Offline mode**: Accept payments with intermittent, limited, or no internet connectivity
- **Tap to Pay**: Accept contactless payments directly on compatible iPhone or Android devices
- **Smart reader apps**: Deploy your Android POS app directly to Stripe smart readers
- **Save cards at POS**: Initiate subscriptions, attach payment details to customer accounts
- **Dynamic reader displays**: Show cart details, line items, and totals on reader screens
- **Receipts**: Prebuilt or custom digital receipts meeting card network rules
- **Tip adjustments**: Support for tipping during checkout
- **Connect integration**: Works with Stripe Connect for platform-based in-person payments
- **PCI PA-DSS & EMVCo certified**: Terminal is certified to EMVCo Level 1 and 2 and PCI PA-DSS standards

## Sales Use Case

Use this document when a customer needs to accept in-person payments (retail, restaurants, events, pop-ups), wants to unify online and offline payment data, is building a custom POS system, or wants to add payment acceptance to a mobile app.

## Client-ready Explanation

Stripe Terminal brings the power of Stripe to in-person payments. You can accept cards, contactless payments, and mobile wallets in your store, at events, or on the go — all managed in the same Stripe Dashboard as your online payments. You can build a fully custom point-of-sale experience with our SDKs, use Tap to Pay on a phone with no extra hardware, or go completely no-code with Standalone Mode. Everything is unified: same reporting, same customer data, same payouts.

## Key Discovery Questions

- What type of business needs in-person payments (retail, restaurant, services, events)?
- What is their expected in-person transaction volume?
- Do they already have a POS system, or are they building one?
- Do they need offline payment capability (unreliable internet)?
- Which countries/regions do they operate in? (Reader availability varies by country)
- Do they want a custom POS integration or a no-code solution?
- Do they need integration with a Stripe Connect platform?
- How many card readers do they need and what form factor (mobile reader vs. smart terminal)?
- Do they need to save customer payment info from in-person purchases for future online use?

## Price

- Domestic card present: 2.7% + $0.05 per transaction
- International cards: +1.5%
- Tap to Pay: +$0.10 per authorization
- Optional P2PE encryption: +$0.05 per authorization
- Hardware: Reader M2 ($59), Reader S710 ($299), Reader S700 ($299)
- Cellular connectivity: $10 per reader per month

## Escalation Notes

- If the customer needs terminal hardware in a country not yet supported, escalate to product team
- For enterprise retail deployments (100+ readers), escalate for volume hardware pricing
- If the customer requires integration with a specific legacy POS system, involve solutions engineering
- For regulated industries (e.g., cannabis, gambling) with in-person payments, escalate for compliance review
