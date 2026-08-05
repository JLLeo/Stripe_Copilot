# Stripe Radar

Product Line: Payment
Product: Radar
Topic: Fraud Detection & Prevention
Source Type: public_doc
Access Level: public
Sales Scenario: fraud_prevention / risk_management
Last Updated: 2026-07-16
Source URL: https://docs.stripe.com/radar

## Summary

Stripe Radar is an AI-powered fraud protection system that evaluates every transaction in real time to assess fraud risk. It uses machine learning models trained on Stripe's global network of millions of businesses to detect and block fraudulent payments before they happen. Radar comes with built-in rules, or can be customized with Radar for Fraud Teams for advanced risk management.

## Key Capabilities

- **Real-time risk scoring**: Every transaction is evaluated and assigned a risk score at payment time
- **Machine learning**: AI models trained across Stripe's entire global transaction network continuously improve fraud detection
- **Dynamic rules engine**: Prebuilt rules that automatically adapt to emerging fraud patterns
- **Radar for Fraud Teams**: Custom rules, manual reviews, what-if analysis, and advanced analytics for teams that want more control
- **Rule actions**: Allow, Block, Review (send for manual review), or Request 3DS authentication
- **Lists**: Maintain allowlists (trusted customers) and blocklists (known fraudsters)
- **Manual reviews**: Queue suspicious payments for human review before fulfillment
- **Risk settings**: Adjust sensitivity — from aggressive filtering to permissive acceptance
- **Radar Sessions**: Extends Radar protection to non-Stripe, tokenized payments
- **Analytics dashboard**: Visualize fraud patterns, dispute rates, and business impact
- **Fraud warning automation**: Auto-respond to customers based on fraud warnings using Workflows
- **Sandbox testing**: Test custom rules against historical data or simulate fraudulent payments
- **3D Secure integration**: Request additional authentication for high-risk transactions

## Sales Use Case

Use this document when a customer asks about fraud protection, mentions high dispute/chargeback rates, wants to reduce payment fraud, needs manual review workflows, or is in an industry with elevated fraud risk.

## Client-ready Explanation

Stripe Radar is like having a dedicated fraud team powered by AI — it evaluates every transaction in real time using machine learning models trained on billions of transactions across Stripe's global network. It blocks fraud before it happens, helps reduce costly chargebacks, and adapts automatically to new fraud patterns. For teams that want more control, Radar for Fraud Teams lets you write custom rules, queue suspicious payments for manual review, and run what-if analyses to test your fraud strategy before deploying it.

## Key Discovery Questions

- What is the customer's current dispute/chargeback rate?
- What types of fraud are they experiencing (card testing, friendly fraud, identity theft, etc.)?
- Do they sell physical goods (which can be intercepted) or digital goods (instant delivery)?
- What is their average transaction value?
- Do they need a hands-off solution (ML-only) or do they want to write custom fraud rules?
- Do they have a fraud/risk team that needs manual review workflows?
- Do they process payments outside of Stripe that also need fraud protection?
- What geographies do they operate in and where do their customers come from?

## Price

- **Standard Radar**: Included free with standard Stripe pricing ($0.05/screened transaction on custom pricing)
- **Radar for Fraud Teams**: $0.02/transaction (standard pricing) or $0.07/transaction (custom pricing)
- **Disputes**: $15.00 per received dispute; $15.00 per manual response (refunded if won)
- **Smart Disputes**: 30% of disputed amount — only charged for won disputes
- **VISA/Mastercard dispute resolution tools**: $15-$29 per use

## Escalation Notes

- If the customer has a dispute rate above 0.75%, escalate for risk assessment and potential dedicated support
- For businesses in high-risk verticals (gambling, crypto, adult content), escalate for compliance and underwriting review
- If the customer needs custom ML models trained on their specific fraud patterns, escalate to Radar product team
- For enterprise customers requiring dedicated fraud analyst support, escalate to Stripe enterprise sales
