# Stripe Subscriptions

Product Line: Revenue
Product: Subscriptions
Topic: Recurring Payment Plans & Lifecycle Management
Source Type: public_doc
Access Level: public
Sales Scenario: saas_subscriptions / recurring_payments / membership_billing
Last Updated: 2026-07-16
Source URL: https://docs.stripe.com/subscriptions

## Summary

Stripe Subscriptions, powered by Stripe Billing, provide a complete framework for building and managing recurring billing models. Subscriptions support trials, proration, automated renewals, plan changes, and the full customer lifecycle — from signup through cancellation. Combined with Stripe Checkout for signup flows and the Customer Portal for self-service management, Subscriptions enable any recurring revenue model.

## Key Capabilities

- **Full subscription lifecycle**: Create, update, pause, resume, cancel, and reactivate subscriptions programmatically
- **Trial periods**: Offer free or paid trials with automatic conversion to full pricing
- **Proration**: Automatically calculate and apply prorated charges for mid-cycle plan changes
- **Subscription schedules**: Pre-schedule plan changes and billing modifications at specific dates
- **Multiple pricing models**: Flat-rate, per-seat, metered usage, tiered (graduated/volume), and multi-currency
- **Automatic payment collection**: Stripe automatically attempts to charge the customer's default payment method at each billing interval
- **Smart Retries**: ML-powered retry logic to recover failed payments and reduce churn
- **Webhooks**: Real-time events for subscription lifecycle changes (created, updated, past_due, canceled, etc.)
- **No-code options**: Pricing Table for signup, Customer Portal for self-service management
- **Coupons & discounts**: Apply percentage or fixed-amount discounts, with or without expiration
- **Multi-product subscriptions**: Bundle multiple products/services in a single subscription
- **Connect support**: SaaS fees and multi-party subscription scenarios via Stripe Connect
- **Salesforce integration**: Sync subscription data with Salesforce via Stripe App for Salesforce
- **Revenue Recognition integration**: Automated revenue recognition compliant with ASC 606 / IFRS 15
- **Tax support**: Calculate and collect tax on subscriptions via Stripe Tax

## Sales Use Case

Use this document when a customer asks specifically about subscription management, recurring billing logic, handling plan changes, trial strategies, churn reduction, or integrating subscriptions with their existing SaaS platform.

## Client-ready Explanation

Stripe Subscriptions gives you a complete recurring billing engine. You define your plans, your customers subscribe through Checkout or your own signup flow, and Stripe handles everything after that: automated billing at each cycle, prorated charges when customers upgrade or downgrade mid-cycle, payment retries when cards fail, and real-time webhooks so your app stays in sync. End customers can manage their own subscriptions — updating payment methods, switching plans, or canceling — through the Customer Portal without contacting your support team.

## Key Discovery Questions

- What subscription billing intervals do they offer (monthly, annual, quarterly)?
- Do they offer free trials or promotional introductory pricing?
- How do they handle customers switching between plans mid-cycle?
- Do they need subscription scheduling (e.g., "switch to annual after 3 months")?
- What is their current churn rate and what are the main causes?
- Do they offer multi-product bundles or add-ons in their subscriptions?
- Do they need the Customer Portal for self-service or will they build their own UI?
- How many active subscribers do they currently have?

## Price

Subscriptions are part of Stripe Billing. Pricing:
- **Pay-as-you-go**: 0.7% of Billing volume
- **Monthly plan**: Starting at $620/month (1-year contract)
Plus standard payment processing fees on subscription charges. There is no additional per-subscription fee.

## Escalation Notes

- If the customer needs complex hybrid pricing (e.g., base fee + tiered usage + one-time add-ons), escalate for solutions architecture review
- For customers with 100K+ active subscribers, escalate for volume Billing pricing
- If the customer is migrating from a competitor (Recurly, Chargebee, Zuora), involve migration specialists
- For enterprise customers needing custom subscription logic not supported by the API, escalate to product team
