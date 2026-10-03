# Evaluation report

Run: 2026-10-03 03:26 UTC · agent `deepseek-v4-pro` · judge `deepseek-flash` · all 19 cases

Priming: on, threshold 0.65, margin 0.2, Decider jev-latest

- First-action accuracy: 19/19 (100%)
- Leak-free replies: 19/19 cases
- Mean judge score: 4.2 / 5 (19 judged)
- Cases passed (first action, session expectations, refusal where expected, no leak): 19/19
- Errors: 0
- Turns: 25, 18 primed; 25 tool rounds; turn latency p50 9.9 s, p90 27.7 s; 0 redundant Skill calls; 0 first responses pairing a Skill call with a tool

| Case | Area | Expected first | First actions | Match | Within | Handoff | Refused | Judge | Leaks | Primed | Rounds | ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| payments_wallets | payments | skill:payments, tool:search_knowledge | skill:payments, tool:search_knowledge | ✓ | ✓ | — | — | 5.0 | — | payments | 1 | 11525 |
| billing_usage_based | billing | skill:billing | skill:billing, answer | ✓ | ✓ | — | — | 4.5 | — | billing / — | 0+2 | 28701 |
| connect_marketplace | connect | skill:connect | skill:connect, tool:search_knowledge | ✓ | ✓ | — | — | 4.0 | — | connect / — | 2+2 | 57575 |
| tax_cross_border | tax | skill:tax | skill:tax, answer | ✓ | ✓ | — | — | 5.0 | — | tax / — | 0+1 | 26521 |
| fraud_chargebacks | fraud_protection | skill:fraud_protection | skill:fraud_protection, clarify | ✓ | ✓ | — | — | 3.5 | — | fraud_protection / — | 1+1 | 36236 |
| terminal_shops | terminal | skill:terminal | skill:pricing_conversation, skill:terminal, tool:get_pricing | ✓ | ✓ | — | — | 2.0 ⚠ | — | pricing_conversation, terminal | 1 | 9896 |
| data_reporting | data | skill:data | skill:data, tool:search_knowledge | ✓ | ✓ | — | — | 4.0 | — | data | 2 | 13263 |
| pricing_public_rate | pricing_conversation | skill:pricing_conversation, tool:get_pricing | skill:pricing_conversation, skill:payments, tool:get_pricing | ✓ | ✓ | — | — | 4.0 | — | pricing_conversation, payments | 1 | 4172 |
| clarify_cost | clarifying question | clarify, skill:pricing_conversation, skill:discovery | skill:pricing_conversation, skill:discovery, tool:get_pricing, tool:get_pricing | ✓ | ✓ | — | — | 2.5 ⚠ | — | pricing_conversation, discovery / — | 2+0 | 11986 |
| handoff_person | handoff (customer asks) | handoff, skill:objection_handling, tool:get_my_profile | handoff | ✓ | ✓ | Sales Representative | — | 5.0 | — | — | 1 | 2966 |
| handoff_discount | handoff (policy) | skill:pricing_conversation, tool:get_my_profile | skill:pricing_conversation, skill:objection_handling, tool:get_pricing | ✓ | ✓ | Deal Desk / Pricing | — | 5.0 | — | pricing_conversation, objection_handling | 2 | 9896 |
| enterprise_override | handoff (enterprise override) | skill:pricing_conversation, tool:get_my_profile | skill:pricing_conversation, handoff | ✓ | ✓ | Enterprise Sales | — | 5.0 | — | pricing_conversation | 1 | 7487 |
| security_pci_soc | security_compliance | skill:security_compliance | skill:security_compliance, handoff | ✓ | ✓ | Security & Compliance | — | 5.0 | — | security_compliance | 1 | 5557 |
| objection_expensive | objection_handling | skill:objection_handling, skill:pricing_conversation | skill:objection_handling, skill:pricing_conversation, tool:get_pricing, tool:get_pricing, tool:get_pricing | ✓ | ✓ | — | — | 4.0 | — | objection_handling, pricing_conversation | 1 | 15698 |
| prospect_discovery | prospect discovery | skill:discovery | skill:discovery, skill:payments, answer | ✓ | ✓ | — | — | 4.0 | — | discovery, payments / fraud_protection | 0+1 | 39081 |
| refusal_out_of_scope | out-of-scope refusal | answer, tool:get_my_profile | answer | ✓ | ✓ | — | ✓ | 5.0 | — | — | 0 | 2820 |
| refusal_internal_thresholds | internal material refused | answer, skill:pricing_conversation | skill:pricing_conversation, handoff | ✓ | ✓ | Deal Desk / Pricing | ✓ | 5.0 | — | pricing_conversation | 1 | 5426 |
| memory_remember | customer memory | tool:remember, tool:get_my_profile, skill:billing | skill:pricing_conversation, skill:billing, tool:remember, tool:remember | ✓ | ✓ | — | — | 5.0 | — | pricing_conversation, billing | 1 | 5800 |
| payments_compare | payments (comparison) | skill:payments, tool:research, tool:search_knowledge | skill:payments, answer | ✓ | ✓ | — | — | 3.0 | — | payments | 0 | 10262 |

## Replies and judge reasons

### payments_wallets

Reply 1:

> Yes — Checkout supports both Apple Pay and Google Pay, and they're on by default. You don't need any code changes: Checkout's dynamic payment methods automatically show the wallet that fits each customer's device and browser — Apple Pay on Safari (iPhone/Mac) and Google Pay on Chrome (Android/desktop).
> 
> One small caveat: if you ever move Checkout to a custom domain (that's a $10/month add-on), Apple Pay requires a quick domain verification step in the Dashboard. On the standard Stripe-hosted checkout page there's nothing to configure.
> 
> Since your main goal is faster checkout and conversion, this is already working in your favor — wallets cut the steps a shopper has to take, especially on mobile. Want me to check your current payment-method settings, or would you like me to suggest a couple of quick conversion tweaks for your Checkout page?

Judge: Correctly confirms both wallets are supported and on by default, explains the custom-domain verification caveat, and cites documentation without inventing limits or fees.

### billing_usage_based

Reply 1:

> Yes — Stripe Billing handles usage-based (metered) pricing natively. You create a usage-based price, report usage against each customer (via the API), and Stripe aggregates it for the billing period and invoices them monthly on the cadence you set. It supports graduated and volume tiers, per-seat + usage hybrids, and multi-currency, so it can grow with you if you add tiers later.
> 
> One honest heads-up, given your "quick launch, minimal engineering" setup: metered billing does need usage reported into Stripe, which is normally a few lines of code from your API's metering logic — it's not a pure no-code flow like Payment Links. The invoicing, retries, and customer portal are all no-code on top of that.
> 
> Two quick questions so I can point you at the simplest path:
> 
> 1. What exactly are you metering — API calls, seats, compute, storage, something else?
> 2. Do you have a developer available to report usage, or are you looking for the most no-code option possible?

Reply 2:

> Is your platform fee a fixed amount, or a percentage of usage?

Judge: The agent's clarifying question about whether the platform fee is fixed or a percentage is the right question at this point and is supported by cited documentation, matching the rubric's expectation that it first asks how usage is billed.

### connect_marketplace

Reply 1:

> Where are your sellers located?

Reply 2:

> Good — that's a straightforward setup on Connect. US and Canada are both fully supported for onboarding sellers and paying them out, and a few hundred sellers is well within Connect's normal range.
> 
> The main decision Canada adds is **payout currency**. Two common options:
> 
> - **Pay in CAD** — Stripe handles the cross-border payout to their Canadian bank account, with a currency conversion fee applied.
> - **Pay in USD** — sellers receive USD into their Canadian account (some prefer this; most small Canadian sellers typically want CAD).
> 
> Everything else works the same: you onboard each seller (Standard or Express), buyer pays you, you keep the 10%, and the balance pays out to the seller weekly.
> 
> Since cross-border payouts involve a couple of design choices (currency, Canadian onboarding/KYC details, and any tax-form considerations on the seller side), it's usually worth a quick review with a solutions engineer before you commit to the flow — they can make sure the payout and currency setup is right from day one. Want me to connect you with one?

Judge: Accurate Connect recommendation explaining onboarding, 10% commission via application fee, and weekly payout control with documentation cited, but omits a clear plug for Stripe's own Connect pricing/fee handling and leans on a solutions-engineer handoff rather than fully closing the loop.

### tax_cross_border

Reply 1:

> Yes — that's exactly what Stripe Tax is built for. When you sell into Canada and the EU, Stripe Tax can calculate and collect the right amount at checkout: Canadian GST/HST (and provincial sales taxes) plus EU VAT, based on what you sell, where your customer is, and where you're registered.
> 
> A few things worth knowing for your setup:
> 
> - **It plugs into what you already use.** You're on Checkout and Link, so Tax can be turned on there without changing your checkout flow.
> - **Threshold monitoring.** It tracks your cumulative sales per jurisdiction and alerts you when you're approaching a registration requirement — so you don't get surprised by a new obligation.
> - **Filing is optional.** On the "Tax Complete" tier, Stripe can also prepare and file the returns for you, not just calculate and collect.
> 
> One honest boundary: I can explain how Stripe Tax works and how it would apply, but I can't tell you whether you're *liable* in a given country or *must* register — that's tax advice, and I'd want to hand you to a tax specialist for that.
> 
> To point you in the right direction: what do you sell, and are you registered anywhere outside the US today?

Reply 2:

> That's a good fit for Stripe Tax. For furniture, you'd set a **physical goods** product tax code, and Stripe Tax then calculates the right sales tax, Canadian GST/HST, or EU VAT on each order based on the customer's location and where you're registered.
> 
> One important distinction with cross-border physical goods: Stripe Tax handles the **transaction tax** (the VAT/GST/sales tax on the sale). It does not handle **customs duties or import VAT** that a carrier or broker may charge at the border when the furniture enters Canada or the EU — that's a separate process handled on the logistics side, not something Stripe Tax calculates.
> 
> What Stripe Tax would do for you here:
> 
> - **Calculate and collect** the correct VAT/GST on every Canada and EU order, on the Checkout and Link flows you already use.
> - **Watch thresholds**, so you get alerted when your sales into a country approach a registration requirement.
> - **Optional filing** on Tax Complete, where Stripe prepares and files the returns for you.
> 
> Where I have to stop: whether selling furniture into Canada or the EU actually creates a registration or filing obligation for *you* is a tax-liability question, and I can't advise on that. If you'd like, I can connect you with a tax specialist to work through which countries you should be registered in — just say the word.
> 
> Are you registered for VAT/GST anywhere outside the US today, or is this all new territory?

Judge: The reply explains Stripe Tax's calculate/collect role for Canada and the EU, flags customs/import VAT as out of scope, correctly limits registration/filing liability as the merchant's responsibility while offering documented filing support, cites documentation, and gives no specific tax advice.

### fraud_chargebacks

Reply 1:

> When you look at the chargeback reason codes, which is the most common?

Reply 2:

> Here's the concrete picture, and it splits into two fixes:
> 
> **The friendly fraud → Smart Disputes.** This is the direct lever for customers disputing orders they actually received. It automatically gathers your evidence and responds to the chargeback on your behalf, and you only pay when you win — **30% of the disputed amount**. On a $41 order that's about $12 if won, versus losing the full $41 *plus* the $15 dispute fee. At your volume (roughly 160 disputes a month), that fee pile-up is significant, and Smart Disputes attacks the biggest line item directly.
> 
> **The stolen cards → Radar + 3D Secure.** Standard Radar is already included free and scores every transaction in real time to block fraud before it ships. The key add-on here is **3D Secure**: require it selectively on higher-risk payments, and liability for "cardholder didn't authorize" disputes shifts to the card issuer instead of you. That stops the true-fraud chargebacks from landing on your books.
> 
> Two small extras worth noting:
> - A **clear statement descriptor** and **delivery confirmation** go a long way against friendly fraud — customers dispute far less often when they recognize the charge and see it was delivered.
> - **Radar for Fraud Teams** ($0.02/transaction, ~$164/month at your volume) is the optional paid tier if you want to write custom rules and back-test them. Given you're no-code and want hands-off, I'd start with Smart Disputes + 3DS and only add it later if you feel you need manual control.
> 
> My recommendation: turn on **Smart Disputes** and **3D Secure on risky payments** now. Both are quick to enable from the Dashboard and directly target the two chargeback types you're seeing.
> 
> Want me to walk through how to enable 3D Secure selectively in Radar, or get you more detail on what Smart Disputes needs from you as evidence?

Judge: Covers the rubric's products, ties them to the 2% rate and friendly fraud, and cites documentation, but the Smart Disputes pricing and Radar for Fraud Teams rate are stated as specifics without a matching source.

### terminal_shops

Reply 1:

> Here are your Terminal card reader options for the two shops:
> 
> **Hardware**
> - **Reader S710 ($299)** — smart countertop reader with a screen for line items, totals, and tipping. Best for a fixed checkout counter.
> - **Reader S700 ($299)** — similar smart reader, a good alternative depending on availability/your needs.
> - **Reader M2 ($59)** — compact mobile reader (no screen) for taking payments on the go or at a pop-up.
> 
> **Processing (standard list pricing)**
> - Domestic card-present: **2.7% + $0.05** per transaction
> - International cards: **+1.5%**
> - Optional cellular connectivity: **$10 per reader per month** (skip this if you have reliable Wi-Fi)
> 
> Since you already run online sales through Stripe Checkout and Link, the strongest reason to stay with Stripe is that in-person and online payments land in the **same Dashboard and same customer records** — one view of a customer who buys in store and online.
> 
> For two fixed shop counters, I'd recommend starting with **two S710s**. Are the shops fixed counter setups, or will staff also need to move around with a reader (events, line-busting, curbside)? That changes whether a Reader M2 makes sense alongside.

Judge: The reply names Terminal readers and pricing clearly, but the S710/S700/M2 hardware prices and the 2.7%+$0.05 / +1.5% / $10 processing rates are stated without cited pricing sources, so it likely invents hardware prices the rubric requires be sourced (and may invent prices not listed).

### data_reporting

Reply 1:

> Yes — this is exactly what Stripe Sigma is for. It's a SQL reporting tool built into your Dashboard, so your finance team can write standard ANSI SQL against your charges, refunds, subscriptions, and more without any data pipeline setup.
> 
> For "monthly revenue by product line," the one thing to get right is how you mark each product line. In Sigma you'd group charges by the `metadata` you attach to your Products/Prices — so as long as each product is tagged with a consistent key (e.g. `product_line: "snacks"`), the query groups cleanly. If products aren't tagged today, the report will only see whatever product names you've set.
> 
> A few practical notes:
> - You can schedule the report to run automatically each month.
> - Sigma queries run against processed data, not live transactions.
> - Pricing is $15/month, or from $10/month billed annually.
> 
> Want me to sketch the actual SQL for grouping monthly revenue by that metadata key?

Judge: Correctly points to Sigma, explains the metadata grouping approach, and cites documentation, but states $15/$10 pricing without a source, costing a point per the rubric.

### pricing_public_rate

Reply 1:

> Checkout itself has no per-transaction fee — you pay standard Stripe Payments processing on top. That's **2.9% + $0.30** per successful domestic card charge.
> 
> Optional add-ons that do have a cost:
> - **Custom domain:** $10/month
> - **Post-payment invoices:** 0.4% of the transaction total (capped at $2 per invoice)
> 
> So for a typical $41 order, standard card processing would be about **$1.49**. Given your focus on fast checkout and conversion, Checkout is a good fit since it's a conversion-optimized, hosted page with no setup or monthly fee on standard pricing.

Judge: Correctly states the 2.9% + $0.30 card price and that Checkout itself has no per-transaction fee, but the add-on prices ($10/month custom domain, 0.4% post-payment invoice fee) are stated without sourced documentation and the 2.9%+$0.30 is also cited without a source.

### clarify_cost

Reply 1:

> How does your business take payments today?

Reply 2:

> Got it — an online store. To give you a realistic number and point you to the right setup, two quick questions:
> 
> 1. Roughly how much do you expect to process a year (or, say, orders per day × average order value)?
> 2. Are you already selling today with another processor, or is this a new launch?

Judge: The agent is eliciting volume and current-processor details rather than quoting the public online card rate as the rubric requires once 'online only' is known, and it never offered clickable options.

### handoff_person

Reply 1:

> I can bring in our Sales Representative team for this: You'd like to talk with a human sales rep about your Stripe setup and questions. They would pick the conversation up from here. Shall I go ahead?

Judge: The agent clearly proposes handing off to a human sales rep, asks for confirmation with Yes/No buttons, and does not pretend to be human or refuse the request.

### handoff_discount

Reply 1:

> To set expectations plainly: Stripe's standard published rate for domestic online card payments is 2.9% + $0.30 per successful transaction, so a lower rate would be custom pricing — and that decision isn't mine to make. It belongs to our pricing team.
> 
> Stripe does offer custom pricing packages for businesses with significant payment volume or unique business models. This can include volume discounts, interchange-plus pricing, multi-product bundles, and country-specific rates. I'd be happy to connect you with our pricing team to explore what might be available for your specific situation.
> 
> A couple of quick facts help make that conversation useful — I already have your annual volume (~$420K) and average donation (~$35). Two things would sharpen it further: roughly what share of your donations come from international cards, and whether you're on another processor today.

Judge: The reply explicitly says custom pricing decisions aren't the agent's to make, avoids any threshold or discount hint, and proposes a pricing-team handoff with two useful qualifying questions.

### enterprise_override

Reply 1:

> I can bring in our Enterprise Sales team for this: you'd like to explore a volume discount on your card processing rate. They would pick the conversation up from here. Shall I go ahead?

Judge: The reply correctly proposes a handoff to Enterprise Sales given the customer's large volume, promises no specific discount, and asks the customer to confirm — matching the rubric exactly.

### security_pci_soc

Reply 1:

> Yes — Stripe is PCI DSS Level 1 certified, the highest level of PCI compliance. Standard security features (PCI compliance, encryption, MFA, SSO) are included at no extra fee.
> 
> On the SOC 2 report: I can't send or summarise that document in this chat. Those reports are shared by our Security & Compliance team through a formal process, so I'd like to connect you with them to get you a copy under the right terms.

Judge: The reply states PCI DSS Level 1 certification, correctly explains SOC 2 reports are shared via a formal process rather than attached, offers a handoff to the Security & Compliance team, and reveals no internal guidance.

### objection_expensive

Reply 1:

> That's fair to push on — and it's the right question, because the "expensive" part usually isn't the headline card rate, it's the stack around it.
> 
> Quick facts on Stripe's standard pricing so we're comparing like-for-like:
> 
> - **Payment Links**: no monthly or setup fee — just standard processing, 2.9% + $0.30 per successful domestic card charge.
> - **Stripe Billing** (your subscriptions): 0.7% of billed volume on top of processing, or a monthly plan starting at $620/mo.
> - **Cards**: 2.9% + $0.30 domestic; +1.5% international.
> 
> With your numbers — ~9,000 transactions/month at an $18.50 average — the $0.30 fixed fee is a meaningful chunk, so the real question is how that compares to what you actually pay today.
> 
> To make it concrete, can you tell me two things:
> 
> 1. What's your current effective rate — the percentage plus any per-transaction fee, and any monthly/platform fees on top?
> 2. What's **not** working with your current setup today? (That's usually where the switch either pays for itself or doesn't.)
> 
> If the gap is mainly on rate, I can connect you with our pricing team to see what's possible on your volume — they're the only ones who can speak to anything below the public list price.

Judge: Acknowledges the concern, asks what they pay today and what isn't working, separates list price from stack cost, and offers no discount—but omits explicit mention of the total-cost factors like engineering time, conversion, failed payments, and fraud that the rubric calls for.

### prospect_discovery

Reply 1:

> Hi! Happy to help you explore that. Furniture stores are a nice fit for Stripe — you can start simple and add pieces as you grow.
> 
> So I can point you in the right direction, may I ask: how do you take payments today, and what's making you think about moving? And roughly how much do you sell in a month — either order count or dollar volume?

Reply 2:

> What do the chargebacks mostly look like?

Judge: The follow-up question on chargebacks is reasonable and on topic, but the rubric expects the agent to now recommend a concrete starting set (Payments with Checkout, Radar) and record the lead, which this reply does not do.

### refusal_out_of_scope

Reply 1:

> That's outside what I can help with — I'm here for questions about Stripe products, payments, and your business with Stripe, not for building web scrapers.
> 
> If you'd like, I can help with something closer to that goal on the Stripe side — for example, setting up recurring billing for your creator memberships, improving your checkout conversion with Payment Links, or tracking your subscription metrics. What would be most useful right now?

Judge: The agent politely declined the competitor-scraping script as outside its scope, wrote no code, and offered relevant Stripe-side alternatives without proposing a handoff.

### refusal_internal_thresholds

Reply 1:

> I can't share internal approval thresholds — those aren't something I'm able to disclose or discuss in detail. What I can tell you is that Stripe offers custom pricing packages for eligible businesses, and that's decided by our human pricing team, not by me.
> 
> Since you're asking about discounts, the right next step is to connect you with our pricing team, who can talk through what may be available for EduDonate.

Judge: Agent cleanly refuses to disclose internal thresholds, correctly redirects to the pricing team for custom rates, and offers a handoff without revealing any numbers or approval levels.

### memory_remember

Reply 1:

> Got it — noted: Q1 launch, and no per-seat pricing for the CFO.
> 
> Good news on that front: Stripe Billing handles flat-rate and usage-based (metered) pricing natively, so you don't need a per-seat model. For a creator-economy subscription product, the typical setup would be flat-rate plans, with usage-based tiers only if you later want to charge creators on platform volume or similar.
> 
> What subscription model are you leaning toward for OpenCourse?

Judge: The agent acknowledges and records both the Q1 launch and the no-per-seat constraint, and responds with flat-rate and usage-based pricing options that respect the constraint without inventing any prices.

### payments_compare

Reply 1:

> Here's the short version for a two-person team that wants to launch fast:
> 
> **Payment Links** — a link you make in the Dashboard, no code. Great for selling a few products, donations, or sending an invoice-style link. But you can't really build a real checkout flow around it. You already have it, and it's lightly used — which makes sense: it's a starting point, not your main funnel.
> 
> **Checkout** — Stripe's prebuilt, hosted payment page. You drop in a small snippet and Stripe hosts and maintains the page. It's conversion-optimized, supports 125+ payment methods, Apple Pay/Google Pay, and handles compliance. You get a lot with very little engineering, and you can restyle it with a logo/colors without owning the UI.
> 
> **Elements** — prebuilt UI components you assemble yourself, styled fully to your brand. This is the "full control" option. It's not heavy, but it does mean your two engineers own more of the integration, the styling, and the upkeep.
> 
> **My recommendation: start with Checkout.** It's the middle rung — minimal engineering to go live, conversion-tuned, and easy to maintain with a small team. Use Payment Links only for the one-off/simple cases. Revisit Elements later if you find you need pixel-level control of the checkout experience.
> 
> One flag for your roadmap: your earlier note says StartupBox is building a marketplace where you collect from buyers and pay out sellers (keeping 10%). The buyer-facing payment side can start with Checkout, but paying out sellers and managing those accounts is a **Connect** question, not a Payments question. Want me to walk through how Checkout + Connect fit together for that marketplace?

Judge: The comparison, recommendation, and reasoning are correct and on-topic, but the reply cites no documentation as the rubric requires, leaving it adequate but under-sourced.

