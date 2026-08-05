# Stripe Billing Overview

Product Line: Revenue
Product: Billing
Topic: Recurring Billing & Subscription Management
Source Type: public_doc
Access Level: public
Sales Scenario: saas_billing / recurring_revenue / subscription_management
Last Updated: 2026-07-16
Source URL: https://docs.stripe.com/billing

## Summary

Stripe Billing enables businesses to automate recurring payments, manage subscriptions, create custom pricing plans, and handle all aspects of the billing lifecycle. It supports flat-rate, per-seat, usage-based, tiered, and multi-currency pricing models. Combined with Stripe Checkout for signups and the Customer Portal for self-service, Billing provides a complete subscription management platform.

## Key Capabilities

- **Subscription management**: Create and manage recurring subscriptions with trials, proration, discounts, and automated renewals
- **Flexible pricing models**: Flat-rate, per-seat, usage-based (metered), tiered (graduated/volume), variable, and multi-currency pricing
- **Usage-based billing**: Bill customers based on metered usage with daily, weekly, monthly, quarterly, or annual billing periods
- **Smart Retries**: Machine-learning-optimized retry scheduling to maximize payment recovery and reduce involuntary churn
- **Automated invoicing**: Generate and send branded invoices automatically each billing cycle
- **Customer Portal**: Self-service portal for customers to manage subscriptions, update payment methods, view invoice history, and cancel/reactivate
- **Pricing Table**: Embeddable pricing table component that directs customers to Stripe Checkout
- **Quotes**: Provide pricing estimates before starting a subscription or sending an invoice
- **Webhooks**: Real-time notifications for subscription events to trigger downstream automations
- **Tax integration**: Built-in Stripe Tax support for automated sales tax, VAT, and GST calculation
- **Coupons & discounts**: Create promotional codes and discount strategies
- **Multi-currency**: Bill customers in their preferred currency

## Sales Use Case

Use this document when a customer needs to set up recurring billing, manage SaaS subscriptions, implement usage-based pricing, reduce involuntary churn, or provide self-service subscription management to their customers.

## Client-ready Explanation

Stripe Billing handles the entire recurring revenue lifecycle — from subscription signup through automated invoicing, payment collection, and customer self-service. It supports any pricing model you can think of: flat monthly fees, per-seat pricing, usage-based metering, tiered plans, or combinations of these. Stripe's machine-learning-driven Smart Retries recover failed payments and reduce churn. And the Customer Portal lets your customers manage their own subscriptions, update payment methods, and view their billing history — with zero code from your team.

## Key Discovery Questions

- What pricing models does the customer use (flat-rate, per-seat, usage-based, tiered)?
- What is their current subscription churn rate (voluntary and involuntary)?
- How do they currently handle failed payments and retries?
- Do their customers need self-service subscription management?
- What billing periods do they offer (monthly, annual, custom)?
- Do they offer trials, promotional pricing, or custom enterprise plans?
- How do they handle upgrades, downgrades, and cancellations?
- Do they need to send quotes before finalizing subscriptions?
- Are they using a billing system currently that they'd need to migrate from?

## Price

- **Pay-as-you-go**: 0.7% of Billing volume (includes on- and off-Stripe transactions)
- **Monthly plan**: Starting at $620/month (1-year contract)
- Plus standard Stripe payment processing fees on transactions

## Escalation Notes

- If the customer has complex usage-based billing needs beyond Stripe Billing's capabilities, suggest evaluating Metronome (Stripe's usage-based billing product)
- For customers processing over $10M/year in subscription billing, escalate for volume pricing
- If the customer needs to migrate a large subscriber base from another billing platform, involve Stripe professional services
- For enterprise plans requiring dedicated implementation support, escalate to enterprise sales
