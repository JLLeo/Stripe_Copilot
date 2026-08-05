# Stripe Sigma

Product Line: Revenue
Product: Sigma
Topic: SQL-based Reporting & Analytics
Source Type: public_doc
Access Level: public
Sales Scenario: custom_reporting / data_analytics / financial_reporting
Last Updated: 2026-07-16
Source URL: https://docs.stripe.com/stripe-data

## Summary

Stripe Sigma is a SQL-based reporting and analytics tool built directly into the Stripe Dashboard. It allows businesses to write custom ANSI SQL queries against their Stripe transactional data — charges, refunds, disputes, subscriptions, invoices, and more — to generate tailored reports. Sigma includes prebuilt query templates, a browsable schema, and integration with data warehouses (Snowflake, Redshift, Databricks).

## Key Capabilities

- **SQL-based querying**: Write custom queries in standard ANSI SQL against your Stripe data
- **Dashboard-native**: Run reports directly in the Stripe Dashboard — no external tools required
- **Prebuilt queries**: Access a library of commonly used SQL queries for quick insights
- **Stripe schema browser**: Explore the Stripe data schema to understand table structures and relationships
- **Custom reports**: Build tailored reports for charges, refunds, disputes, subscriptions, invoices, payouts, and more
- **Scheduled reports**: Set up recurring report generation and sync with external data warehouses
- **Data warehouse export**: Export query results to Snowflake, Redshift, or Databricks
- **Query migration tools**: Migrate queries between engine versions (Presto v334 → Trino v414)
- **Operational & finance metrics**: Analyze transaction patterns, monitor business growth, track customer behavior, and generate financial reports

## Sales Use Case

Use this document when a customer asks about accessing their Stripe data for custom reporting, needs to build financial dashboards, wants to analyze transaction patterns, is frustrated with CSV exports from the Dashboard, or needs to answer complex questions about their payment data.

## Client-ready Explanation

Stripe Sigma gives you the power of SQL directly on your Stripe data — no data pipeline setup required. Want to know which payment methods have the highest failure rate? Which customers have the most disputes? How your monthly recurring revenue is trending? Write a SQL query in the Dashboard and get answers in seconds. Sigma includes prebuilt queries so you don't have to start from scratch, and you can schedule reports to run automatically. For deeper analysis, you can export results to your data warehouse.

## Key Discovery Questions

- What questions about their payment data is the customer trying to answer?
- How are they currently getting data out of Stripe (CSV exports, API, manual)?
- Do they have SQL expertise on their team?
- What specific metrics or reports do they need (MRR, churn, dispute rates, payment method performance)?
- Do they need ad-hoc analysis or scheduled/recurring reports?
- Do they use a data warehouse (Snowflake, Redshift, Databricks) that they'd want to integrate with?
- How large is their transaction volume? (Affects query performance expectations)

## Price

- **Monthly**: $15/month
- **Annual**: Starting at $10/month (billed annually)

## Escalation Notes

- If the customer needs real-time data (Sigma queries run against processed data, not live), discuss Data Pipeline for warehouse integration
- For customers with very large datasets and complex query needs, suggest evaluating Data Pipeline + their own BI tools
- If the customer doesn't have SQL expertise, discuss whether Dashboard reports or prebuilt Sigma queries meet their needs
- For enterprise customers needing custom data models or dedicated analytics support, escalate to Stripe data team
