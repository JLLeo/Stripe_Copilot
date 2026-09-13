---
name: data
description: Reporting and data — Sigma SQL reporting in the Dashboard; Data Pipeline exports to Snowflake, BigQuery, Redshift, Databricks or cloud storage. Load for analytics, reconciliation, close.
---

# Data — Sigma and Data Pipeline

Two products answer "how do we analyse our Stripe data": Sigma for querying it
inside Stripe, Data Pipeline for landing it in the business's own warehouse.

## Sigma

- Write ANSI SQL against Stripe data (charges, refunds, disputes,
  subscriptions, invoices, payouts, customers…) directly in the Dashboard.
- Prebuilt query library and a schema browser to get started.
- Scheduled reports; export results to Snowflake, Redshift or Databricks.
- Best for finance and ops teams who want answers without an engineering project.

## Data Pipeline

- No-code, scheduled sync of all Stripe data to Snowflake, Amazon Redshift,
  Databricks, Google BigQuery, Amazon S3, Google Cloud Storage or Azure Blob
  Storage.
- Join Stripe data with CRM, ERP and product analytics; feed the financial
  close; use Tableau, Looker, Power BI or any BI tool on top.
- Best for businesses that already run a warehouse and want Stripe in it
  without building or maintaining an ETL job.

## Which to lead with

Ask where the analysis will happen. In Stripe → Sigma. In their warehouse →
Data Pipeline. Many mature businesses use both: Sigma for quick questions,
Data Pipeline for the system of record.

## What to establish before recommending

- Who asks the questions — finance, ops, data team — and what tools do they use today?
- Do they have a warehouse, and which one?
- What is the pain: reconciliation, month-end close, churn analysis, payout matching?
- Volume of Stripe activity (from the profile) — the more products they use, the more the data matters.

## Pricing

Sigma: $15/month, or from $10/month billed annually. Data Pipeline: $65/month,
or from $50/month billed annually. Confirm with `get_pricing`.

## When to bring in a human

Custom data contracts, very high data volumes, or security review of the
warehouse integration — offer a solutions engineer or the security team.
