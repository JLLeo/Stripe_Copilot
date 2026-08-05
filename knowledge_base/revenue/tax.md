# Stripe Tax

Product Line: Revenue
Product: Tax
Topic: Automated Sales Tax, VAT & GST Compliance
Source Type: public_doc
Access Level: public
Sales Scenario: tax_compliance / global_sales_tax / vat_management
Last Updated: 2026-07-16
Source URL: https://docs.stripe.com/tax

## Summary

Stripe Tax automates sales tax, VAT, and GST calculation and collection on every transaction. It determines the correct tax rate based on product type and customer/business location, monitors registration thresholds, and can even handle tax registration and filing on your behalf. Stripe Tax works across all Stripe payment surfaces — Checkout, Payment Links, Invoicing, Subscriptions, and custom Payment Intents integrations — and also supports off-Stripe transactions.

## Key Capabilities

- **Automatic tax calculation**: Calculates the correct sales tax, VAT, or GST rate based on product tax codes, customer location, and business registration locations
- **Global coverage**: Supports tax calculation across multiple countries and jurisdictions — US sales tax, EU VAT, UK VAT, AU/NZ GST, and more
- **Product tax codes**: Categorize products and services for correct tax treatment (e.g., SaaS vs. physical goods vs. digital services)
- **Threshold monitoring**: Tracks cumulative sales against local tax registration thresholds and alerts you when registration is required
- **Registration management**: Manage global tax registrations; Stripe can register for sales tax on your behalf
- **Automated filing**: (Tax Complete) Stripe handles tax return preparation and filing with local authorities
- **Multi-surface integration**: Works with Checkout, Payment Links, Invoicing, Subscriptions, and custom Payment Intents
- **Off-Stripe transactions**: Calculate and report tax on payments processed outside Stripe
- **Connect integration**: Calculate tax on behalf of connected accounts in marketplace/platform scenarios
- **Tax reporting**: Generate tax reports for filing and audit purposes

## Sales Use Case

Use this document when a customer asks about managing sales tax/VAT across multiple jurisdictions, needs to automate tax compliance, is worried about crossing tax registration thresholds in new markets, or wants to reduce the manual effort of tax calculation and filing.

## Client-ready Explanation

Stripe Tax makes sales tax compliance effortless. It automatically calculates the right tax on every transaction — whether it's US sales tax, EU VAT, UK VAT, or Australian GST — based on what you're selling and where your customer is. It monitors when you're approaching registration thresholds in new jurisdictions, can handle the actual tax registration for you, and with Tax Complete, Stripe will even prepare and file your tax returns. Best of all, it works everywhere you already use Stripe: Checkout, Payment Links, Invoicing, and Subscriptions.

## Key Discovery Questions

- Where is the customer based and where do their customers come from (US, EU, UK, APAC)?
- What types of products do they sell (SaaS, physical goods, digital downloads, services)?
- Are they currently registered for tax in any jurisdictions? Which ones?
- How do they currently calculate and file taxes?
- Are they approaching sales thresholds in any new states or countries?
- Do they need automated filing (Tax Complete) or just calculation (Tax Basic)?
- Do they operate a marketplace/platform that needs to handle tax for connected accounts?
- Do they have tax-exempt customers (B2B with valid tax IDs)?

## Price

- **Tax Complete**: Starting at $90/month (1-year contract) — includes monitoring, registrations, calculations, and filings
- **Tax Basic (no-code)**: 0.5% per transaction where you're registered
- **Tax Basic (API)**: $0.50 per transaction; each includes 10 calculation API calls ($0.05 per additional call)

## Escalation Notes

- If the customer has complex multi-entity, multi-country tax structures, escalate to Stripe Tax specialists
- For enterprise customers needing custom tax integration or dedicated support, escalate to enterprise sales
- If the customer operates in regions with unique tax regimes not covered by Stripe Tax, escalate to product team
- For customers under audit who need historical tax data support, escalate to compliance team
