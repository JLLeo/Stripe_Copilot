# Stripe Payments Overview

Product Line: Payment
Product: Payments
Topic: Payment Processing Platform
Source Type: public_doc
Access Level: public
Sales Scenario: payment_processing / online_payments
Last Updated: 2026-07-16
Source URL: https://docs.stripe.com/payments

## Summary

Stripe Payments is a financial infrastructure platform that enables businesses to accept payments online and in person, embed financial services, and power custom revenue models. It provides APIs, prebuilt UI components, and no-code solutions for payment processing across 135+ currencies and 100+ payment methods.

## Key Capabilities

- **Online payments**: Accept payments via prebuilt checkout pages (Checkout), no-code links (Payment Links), or custom payment forms (Elements + Payment Intents API)
- **In-person payments**: Stripe Terminal with SDKs and card readers for point-of-sale
- **Subscriptions & recurring billing**: Recurring payments, trial periods, proration, and discount management via Stripe Billing
- **Invoicing**: Dashboard invoicing, hosted invoice pages, and Invoicing API
- **100+ payment methods**: Cards, bank debits, bank redirects, wallets (Apple Pay, Google Pay), BNPL (Klarna, Afterpay), crypto stablecoins, and Link (Stripe's digital wallet)
- **Dynamic payment methods**: Automatically orders and displays the most relevant payment methods per customer — no code required
- **Fraud protection**: Stripe Radar provides AI-based fraud detection with real-time risk scoring
- **Platform support**: Stripe Connect enables marketplaces and SaaS platforms to manage payments between multiple parties
- **Global reach**: 135+ currencies, 30+ languages, local acquiring in 46+ countries
- **Adaptive Pricing**: Automatically localizes pricing based on customer location, showing local currency

## Sales Use Case

Use this document as the starting point when a customer asks about Stripe's overall payment capabilities, wants to understand the product ecosystem, or needs to evaluate Stripe against other payment processors. It sets the stage for deeper discussions about specific products.

## Client-ready Explanation

Stripe is a comprehensive payment platform that lets you accept payments everywhere your customers are — online, in person, and globally. It is used by millions of businesses from startups to Fortune 500 companies. Stripe handles everything from the payment form to fraud detection to compliance, so your engineering team can focus on building your product rather than managing payment infrastructure.

## Key Discovery Questions

- What types of payments does the customer need to accept (online, in-person, both)?
- What payment methods do their customers expect (cards, wallets, bank transfers, BNPL)?
- Do they need recurring billing or one-time payments?
- Are they a marketplace/platform that needs to pay out to third parties?
- What countries/currencies do they operate in?
- What is their current payment processing volume?
- Do they have engineering resources for integration, or do they prefer no-code options?

## Price

Stripe Payments standard pricing is 2.9% + $0.30 per successful domestic card transaction. Surcharges apply for international cards (+1.5%), manually entered cards (+0.5%), and currency conversion (+1%). Refunds do not incur additional fees. Custom pricing is available for businesses with large payment volume or unique business models. See the [Stripe Pricing page](https://stripe.com/pricing) for complete details.

## Escalation Notes

- If the customer processes more than $1M/year or has a unique business model, escalate for custom pricing evaluation
- If the customer needs specific regional payment methods not currently supported, escalate to product team
- If the customer asks about guaranteed uptime SLAs or enterprise compliance requirements, escalate to Stripe enterprise sales
- For complex marketplace/platform scenarios, involve a Connect specialist
