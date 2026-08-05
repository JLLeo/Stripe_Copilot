# Stripe Elements

Product Line: Payment
Product: Elements
Topic: Customizable Payment UI Components
Source Type: public_doc
Access Level: public
Sales Scenario: custom_checkout / full_ui_control
Last Updated: 2026-07-16
Source URL: https://docs.stripe.com/payments/elements

## Summary

Stripe Elements is a set of prebuilt, secure, PCI-compliant UI components for building fully customized web checkout flows. Elements tokenize sensitive payment details client-side — meaning card data never touches the merchant's server. They provide full CSS control via the Appearance API and access to 100+ global payment methods.

## Key Capabilities

- **Prebuilt UI components**: Drop-in-ready form elements for payment collection, address input, wallet display, currency selection, and tax ID collection
- **PCI-compliant by default**: Sensitive payment data is tokenized client-side — never touches your server
- **Full customization**: Complete CSS control via the Appearance API — theming, fonts, colors, border radii, spacing
- **100+ payment methods**: Global coverage including wallets (Apple Pay, Google Pay), BNPL, bank debits, and more
- **Link integration**: Customers can use saved payment methods for faster checkout
- **Dynamic payment methods**: Automatically shows the most relevant options for each customer
- **Built-in validation & error handling**: Localized forms with real-time validation and error messages
- **Address collection**: Full or partial billing address collection with any payment method
- **Express Checkout Element**: Display wallets like Apple Pay, Google Pay, and PayPal
- **Currency Selector Element**: Let customers pay in their local currency
- **Saved payment methods**: Save, reuse, and manage cards and bank accounts for returning customers
- **Card brand filtering**: Control which card brands you accept

### Available Elements

| Element | Purpose |
|---|---|
| Payment Element | Accept payments via one or multiple methods |
| Express Checkout Element | Display wallets (Apple Pay, Google Pay, PayPal) |
| Contact Details Element | Auto-fill customer details via Link |
| Address Element | Collect address info with Link integration |
| Payment Method Messaging Element | Inform customers about BNPL plans |
| Currency Selector Element | Let customers pay in local currency |
| Tax ID Element | Collect business tax IDs for invoices/VAT |

### Elements vs. Checkout

Elements use the Checkout Sessions API (recommended) for full checkout management including line items, tax, discounts, and subscriptions, or the Payment Intents API for deeper control over individual payment steps. The Checkout Sessions API is recommended for most integrations — it requires less code and enables features like Adaptive Pricing.

## Sales Use Case

Use this document when a customer wants complete control over their checkout UI design, needs to embed payment forms deeply within a custom experience, or has specific UX requirements that prebuilt checkout pages cannot accommodate.

## Client-ready Explanation

Stripe Elements gives your development team prebuilt, secure payment form components that they can style to perfectly match your brand and UX. Your customers get a seamless, on-brand payment experience without ever leaving your site, while Stripe handles the sensitive PCI compliance work behind the scenes. It's the best choice when you need full design control and have engineering resources available.

## Key Discovery Questions

- How much control does the customer need over checkout UI/UX (brand colors vs. pixel-perfect custom design)?
- Do they have frontend engineering resources available?
- Do they need Adaptive Pricing and dynamic payment methods? (Requires Checkout Sessions API mode)
- Which payment methods are most important for their customers?
- Do they need to save customer payment methods for future use?
- Are they building for web, mobile, or both?
- What framework are they using (React, vanilla JS, etc.)?

## Price

Elements are included at no extra charge with standard Stripe Payments processing (2.9% + $0.30 per successful domestic card charge). There is no additional fee for using Elements.

## Escalation Notes

- If the customer has limited engineering resources, suggest evaluating Stripe Checkout instead for a lower-complexity integration
- For mobile-native checkout requirements, refer to the Mobile Payment Element and Terminal SDKs
- If the customer needs highly specialized payment method support not covered by Elements, escalate to product team
- For enterprise teams needing dedicated integration support, escalate to Stripe professional services
