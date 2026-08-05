# Stripe Invoicing

Product Line: Revenue
Product: Invoicing
Topic: Invoice Creation & Accounts Receivable
Source Type: public_doc
Access Level: public
Sales Scenario: b2b_invoicing / accounts_receivable / invoice_management
Last Updated: 2026-07-16
Source URL: https://docs.stripe.com/invoicing

## Summary

Stripe Invoicing enables businesses to create, send, and manage invoices for one-time and recurring payments. Invoices track payment status from draft through paid, with automated collection tools including Smart Retries, dunning emails, and auto-charging of saved payment methods. The hosted invoice page supports 40+ payment methods, 30+ languages, and is fully customizable with brand elements.

## Key Capabilities

- **Dashboard invoicing**: Create and send invoices directly from the Stripe Dashboard — no code required
- **API invoicing**: Programmatically create and manage invoices for automated workflows
- **Hosted invoice page**: Stripe-hosted payment page for each invoice, supporting 40+ payment methods and 30+ languages
- **Automatic collection**: Smart Retries and automated dunning emails to maximize payment rates
- **Auto-charge**: Automatically charge the customer's saved payment method when an invoice is due
- **Invoice customization**: Editable template with custom icons, brand colors, payment terms, page sizes, memo, and footer fields
- **Partial payments / payment plans**: Let customers pay invoices in installments
- **Quotes** (Invoicing Plus): Provide pricing estimates, then convert to invoice once finalized — supports renegotiation
- **Multi-currency support**: Set billable currency per customer
- **Automatic reconciliation**: Stripe matches incoming bank payments to invoices automatically
- **Virtual bank account numbers**: Generate unique account numbers via API for easy payment matching
- **Tax support**: Integrated with Stripe Tax for automatic tax calculation on invoices
- **Customer Portal integration**: Let customers view and pay invoices through a self-service portal
- **Credit notes**: Issue credit notes against invoices for refunds or adjustments

### Invoicing vs. Payment Links

| Feature | Invoicing | Payment Links |
|---|---|---|
| Target recipient | Specific customer | Anyone with the link |
| Reusability | Can duplicate | Reusable multiple times |
| Partial payments | ✓ Yes | ✗ No |
| Quotes/estimates | ✓ Yes | ✗ No |
| Customer-chosen amount | ✗ No | ✓ Yes |
| Upsells | ✗ No | ✓ Yes |
| Customization | Editable template | Limited presets |

## Sales Use Case

Use this document when a customer needs to send invoices to specific clients, manage accounts receivable, offer payment terms, handle B2B billing, send quotes before invoicing, or automate payment collection for service-based businesses.

## Client-ready Explanation

Stripe Invoicing is a complete accounts receivable solution. You can create professional, branded invoices from the Dashboard or via API, send them to your customers, and let Stripe handle the rest — automated payment reminders, Smart Retries for failed payments, and automatic reconciliation when payments come in. Your customers get a beautiful, Stripe-hosted invoice page where they can pay instantly with 40+ payment methods. For B2B companies that need to send quotes, offer payment terms, or accept partial payments, Invoicing Plus has you covered.

## Key Discovery Questions

- Does the customer bill specific clients (B2B) or sell to anyone (B2C)?
- What are their typical invoice amounts and monthly invoice volume?
- Do they need to send quotes before converting to invoices?
- Do they offer payment terms (Net 15, Net 30)?
- Do they need partial payment / installment plans?
- How much invoice customization do they need (branding, custom fields, templates)?
- Do they need automated dunning/reminder emails for overdue invoices?
- Do they need to reconcile bank transfer payments automatically?
- Are they using an existing invoicing system they need to migrate from?

## Price

- **Starter**: 0.4% per paid invoice
- **Invoicing Plus** (includes Quotes): Contact sales or see pricing page
- Plus standard payment processing fees on invoice payments
- No monthly fee for basic Invoicing

## Escalation Notes

- For customers with complex multi-entity invoicing needs (multiple legal entities, intercompany), escalate to enterprise sales
- If the customer requires EDI (Electronic Data Interchange) invoicing for enterprise clients, escalate to product team
- For high-volume invoicing (10K+ invoices/month), escalate for volume pricing
- If the customer needs industry-specific invoice compliance (e.g., healthcare, government), escalate for compliance review
