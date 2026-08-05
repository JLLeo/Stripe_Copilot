# Stripe Connect

Product Line: Payment
Product: Connect
Topic: Platform & Marketplace Payments
Source Type: public_doc
Access Level: public
Sales Scenario: marketplace / saas_platform / multi_party_payments
Last Updated: 2026-07-16
Source URL: https://docs.stripe.com/connect

## Summary

Stripe Connect is a set of APIs and tools for building platforms, marketplaces, and SaaS businesses that manage payments and move money between multiple parties. It enables platforms to collect payments from end customers, automatically split and route funds to sellers or service providers, onboard and verify third-party accounts (KYC/KYB), and manage payouts — all while the platform controls pricing and fee structures.

## Key Capabilities

- **Multi-party payments**: Collect funds from customers and split payments between platform fees and seller/service provider payouts
- **Flexible business models**: Support for SaaS platforms (Shopify model), marketplaces (Uber/Airbnb model), on-demand services, crowdfunding, and global payout platforms
- **Connected account onboarding**: Standard, Express, and Custom onboarding flows with KYC/KYB verification built in
- **Account capabilities**: Granular control over what each connected account can do (card payments, transfers, payouts)
- **Platform pricing control**: Set custom processing fees for connected accounts via the platform pricing tool (starting at 0.25% markup)
- **Payout management**: Configure payout schedules (daily, weekly, monthly, manual), manage external bank accounts, and handle international payouts
- **Dashboard management**: Review and take action on connected accounts from the Stripe Dashboard
- **Connect embedded components**: Embed Stripe Dashboard functionality (onboarding, payments, payouts) directly into your platform's UI
- **Tax integration**: Stripe Tax works with Connect for tax calculation on behalf of connected accounts
- **Radar integration**: Fraud protection extends to connected account transactions
- **Revenue Recognition**: Automated revenue recognition for platform fees and pass-through transactions
- **Global reach**: Onboard and pay out to connected accounts worldwide

### Business Model Types

| Model | Description | Example |
|---|---|---|
| **SaaS Platform** | Platform enables businesses to accept payments from their own customers | Shopify, Squarespace |
| **Marketplace** | Platform collects from buyers and pays out to sellers/service providers | Uber, Airbnb, Fiverr |
| **Accounts v2** | Unified identity per connected account with multiple role configurations | Modern platforms |

## Sales Use Case

Use this document when a customer needs to facilitate payments between multiple parties, operates a marketplace or platform business model, wants to onboard and pay out sellers/service providers, needs to monetize payments with platform fees, or requires KYC/KYB verification for third-party accounts.

## Client-ready Explanation

Stripe Connect is how platforms like Shopify, DoorDash, and Lyft manage payments at scale. It handles the entire flow: onboarding sellers with built-in identity verification, processing payments from end customers, automatically splitting funds between what goes to the seller and what's your platform fee, and managing payouts to sellers' bank accounts globally. You control your pricing — set your own fees on top of Stripe's processing costs — and Stripe handles the regulatory, compliance, and operational complexity behind the scenes.

## Key Discovery Questions

- What is their business model (marketplace, SaaS platform, service marketplace, crowdfunding)?
- Who are they paying out to (individual sellers, businesses, service providers)?
- What countries do their sellers/service providers operate in?
- How do they want to monetize payments (flat fee, percentage, subscription)?
- What level of onboarding experience do they need (Stripe-hosted, embedded in their app, fully custom)?
- Do they need to hold funds before paying out (escrow, milestone payments)?
- What is their expected transaction volume and average transaction size?
- Do they have existing sellers they need to migrate onto the platform?
- Do they need to handle tax, fraud, or disputes for their connected accounts?

## Price

Stripe Connect pricing depends on your business model. Contact Stripe sales for custom Connect pricing. Platform pricing tool allows you to set your own fees starting at a 0.25% markup on processing. Standard Stripe processing fees apply to underlying transactions.

## Escalation Notes

- **Always escalate complex Connect scenarios** — Connect is Stripe's most architecturally complex product and incorrect configuration can have significant financial and compliance implications
- For platforms with cross-border payout requirements involving 50+ countries, escalate to Connect specialists
- If the customer operates in a regulated industry (fintech, lending, investments), escalate for compliance review
- For platforms processing $10M+/year through Connect, escalate for dedicated account management
- If the customer needs custom onboarding forms or verification flows beyond the standard options, escalate to solutions engineering
