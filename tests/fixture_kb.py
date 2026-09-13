"""A four-document knowledge base for tests: three public, one internal that must never surface."""

INTERNAL_MARKER = "DISCOUNT-LADDER-SECRET"

DOCS = {
    "payment/checkout.md": """# Stripe Checkout

Product Line: Payment
Product: Checkout
Topic: Hosted payment page
Source Type: public_doc
Access Level: public
Source URL: https://stripe.com/payments/checkout

## Summary

Stripe Checkout is a prebuilt, Stripe-hosted payment page that accepts cards, wallets and local payment methods.

## Key Capabilities

- Hosted page with Apple Pay and Google Pay wallets
- Adaptive Pricing shows the customer's local currency
- Supports subscriptions and one-time payments

## Price

Checkout is included with standard processing at 2.9% + $0.30.
""",
    "payment/radar.md": """# Stripe Radar

Product Line: Payment
Product: Radar
Topic: Fraud prevention
Source Type: public_doc
Access Level: public
Source URL: https://stripe.com/radar

## Summary

Stripe Radar scores every payment for fraud risk with machine learning trained on the Stripe network.

## Key Capabilities

- Real-time fraud risk scoring on every transaction
- Rules to block, allow or review payments
- Radar for Fraud Teams adds manual review queues
""",
    "revenue/billing_overview.md": """# Stripe Billing Overview

Product Line: Revenue
Product: Billing
Topic: Recurring billing
Source Type: public_doc
Access Level: public
Source URL: https://stripe.com/billing

## Summary

Stripe Billing automates subscriptions, invoices and usage-based recurring revenue.

## Key Capabilities

- Smart Retries recover failed subscription payments
- Customer portal for plan changes
""",
    "pricing/custom_pricing_policy.md": f"""# Mock Internal: Custom Pricing Policy

Product Line: Pricing
Product: Pricing
Topic: Internal Custom Pricing Guidelines
Source Type: mock_policy
Access Level: internal_mock
Source URL: internal://pricing-policy

## Summary

INTERNAL ONLY. Discount ladder {INTERNAL_MARKER}: offer 10% at $1M, 20% at $5M.
""",
}
