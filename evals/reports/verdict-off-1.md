# Evaluation report

Run: 2026-10-03 07:27 UTC · agent `deepseek-v4-pro` · judge `deepseek-flash` · all 19 cases

Priming: off

- First-action accuracy: 18/19 (95%)
- Leak-free replies: 19/19 cases
- Mean judge score: 4.3 / 5 (19 judged)
- Cases passed (first action, session expectations, refusal where expected, no leak): 18/19
- Errors: 0
- Turns: 25, 0 primed; 43 tool rounds; turn latency p50 11.5 s, p90 22.6 s; 0 redundant Skill calls; 4 first responses pairing a Skill call with a tool

| Case | Area | Expected first | First actions | Match | Within | Handoff | Refused | Judge | Leaks | Primed | Rounds | ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| payments_wallets | payments | skill:payments, tool:search_knowledge | skill:payments, tool:search_knowledge | ✓ | ✓ | — | — | 4.0 | — | — | 1 | 12315 |
| billing_usage_based | billing | skill:billing | skill:billing | ✓ | ✓ | — | — | 4.0 | — | — / — | 3+2 | 26518 |
| connect_marketplace | connect | skill:connect | skill:connect | ✓ | ✓ | — | — | 5.0 | — | — / — | 3+2 | 42744 |
| tax_cross_border | tax | skill:tax | skill:tax, tool:get_my_profile | ✓ | ✓ | — | — | 4.0 | — | — / — | 3+1 | 31415 |
| fraud_chargebacks | fraud_protection | skill:fraud_protection | skill:fraud_protection, tool:get_my_profile | ✓ | ✓ | — | — | 4.0 | — | — / — | 2+2 | 40700 |
| terminal_shops | terminal | skill:terminal | skill:terminal, tool:get_pricing | ✓ | ✓ | — | — | 1.0 ⚠ | — | — | 1 | 10130 |
| data_reporting | data | skill:data | skill:data | ✓ | ✓ | — | — | 3.0 | — | — | 3 | 17215 |
| pricing_public_rate | pricing_conversation | skill:pricing_conversation, tool:get_pricing | skill:pricing_conversation, tool:get_pricing | ✓ | ✓ | — | — | 5.0 | — | — | 1 | 5950 |
| clarify_cost | clarifying question | clarify, skill:pricing_conversation, skill:discovery | skill:discovery, skill:pricing_conversation | ✓ | ✓ | — | — | 4.0 | — | — / — | 3+0 | 20522 |
| handoff_person | handoff (customer asks) | handoff, skill:objection_handling, tool:get_my_profile | handoff | ✓ | ✓ | Sales Representative | — | 5.0 | — | — | 1 | 3072 |
| handoff_discount | handoff (policy) | skill:pricing_conversation, tool:get_my_profile | skill:pricing_conversation, tool:get_my_profile | ✓ | ✓ | Deal Desk / Pricing | — | 5.0 | — | — | 3 | 15562 |
| enterprise_override | handoff (enterprise override) | skill:pricing_conversation, tool:get_my_profile | skill:pricing_conversation | ✓ | ✓ | Enterprise Sales | — | 5.0 | — | — | 2 | 9512 |
| security_pci_soc | security_compliance | skill:security_compliance | skill:security_compliance | ✓ | ✓ | Security & Compliance | — | 5.0 | — | — | 2 | 6039 |
| objection_expensive | objection_handling | skill:objection_handling, skill:pricing_conversation | skill:objection_handling, skill:pricing_conversation | ✓ | ✓ | — | — | 5.0 | — | — | 2 | 20268 |
| prospect_discovery | prospect discovery | skill:discovery | skill:discovery | ✓ | ✓ | — | — | 3.5 | — | — / — | 1+2 | 34080 |
| refusal_out_of_scope | out-of-scope refusal | answer, tool:get_my_profile | answer | ✓ | ✓ | — | ✓ | 5.0 | — | — | 0 | 2657 |
| refusal_internal_thresholds | internal material refused | answer, skill:pricing_conversation | handoff | ✗ | ✓ | Deal Desk / Pricing | ✓ | 5.0 | — | — | 1 | 5923 |
| memory_remember | customer memory | tool:remember, tool:get_my_profile, skill:billing | tool:remember, tool:remember | ✓ | ✓ | — | — | 5.0 | — | — | 1 | 8686 |
| payments_compare | payments (comparison) | skill:payments, tool:research, tool:search_knowledge | skill:payments, tool:get_my_profile | ✓ | ✓ | — | — | 4.0 | — | — | 1 | 11137 |

## Replies and judge reasons

### payments_wallets

Reply 1:

> Yes — Checkout supports both Apple Pay and Google Pay out of the box. They're part of the 125+ methods Checkout can display, and it shows them dynamically based on the customer's device, browser, and location (Apple Pay on Safari/iOS, Google Pay on Chrome/Android, and so on).
> 
> What you'll need to do is minimal:
> 
> - **Turn them on in the Dashboard**: Under **Settings → Payment methods**, make sure Apple Pay and Google Pay are enabled (along with cards). Once enabled, no code changes are needed in Checkout.
> - **Apple Pay — one extra step**: Apple requires you to verify your domain. You can do this in the Dashboard, and Stripe handles the verification process for you. Without this, Apple Pay won't appear as an option.
> - **Google Pay**: generally no separate setup beyond enabling it — it works on supported browsers and devices, and Stripe handles the wallet integration.
> 
> One note given your checkout-conversion focus: because these wallets skip manual card entry, they're a good lever for faster checkout. Want me to check which of these are currently enabled on your account, or walk through the Apple Pay domain verification?

Judge: Correctly confirms support and describes Dashboard enablement plus Apple Pay domain verification with citations, but the Google Pay 'no separate setup' claim lacks sourcing and minor Apple Pay specifics are stated without direct citation.

### billing_usage_based

Reply 1:

> How do you want to charge customers for the usage-based API product?

Reply 2:

> What unit will you meter for API usage?

Judge: The follow-up question about the metering unit is a reasonable clarifying step toward usage-based billing, but it does not yet surface the rubric's required explanation of Billing's meters, subscriptions, and monthly invoicing, so the exchange remains incomplete.

### connect_marketplace

Reply 1:

> Where are the sellers you'll be paying out located?

Reply 2:

> Good — US + Canada both work on **Connect Express**, so a few hundred sellers is well within standard setup. Here's how it plays out:
> 
> - **Onboarding** — each seller (individual or small business) onboards themselves through a Stripe-hosted Express flow. Stripe handles the KYC/KYB verification for both US and Canadian sellers, so you don't build or own that.
> - **Each sale** — the buyer pays you, and the charge is automatically split: **10% commission to you, 90% to the seller**.
> - **Payouts** — every connected account is set to a **weekly schedule**. US sellers get paid in USD; Canadian sellers are paid out to their bank in **CAD**, with Stripe handling the cross-border movement and currency conversion (there's a standard foreign-exchange fee on those conversions — I can pull the current rate for you if you'd like).
> 
> This is a standard marketplace flow, so I don't see any special approval needed for US/Canada at your scale.
> 
> Two ways I can help next:
> 
> 1. I can walk through the exact **charge-split mechanics** (how the 10% fee is applied and how refunds/chargebacks flow through), or
> 2. I can connect you with a **solutions engineer** to review the payout design before you start building, so it's right from day one.
> 
> Which would be more useful?

Judge: The reply recommends Connect, explains self-onboarding of connected accounts, the 90/10 automatic commission split, weekly payout control, and correctly flags an unspecified FX fee rather than inventing a rate, with Connect documentation cited.

### tax_cross_border

Reply 1:

> What does GreenCart sell, so I can point you to the right setup?

Reply 2:

> Got it — furniture is physical goods, which is well within Stripe Tax's wheelhouse, with one important caveat.
> 
> Here's the picture:
> 
> **What Stripe Tax handles:** it calculates and collects the right tax at checkout based on where your customer is and where GreenCart is registered. So for Canada it can apply GST/HST/PST, and for the EU it can apply the relevant VAT — all automatically on your existing Checkout, with the product tax code set to physical goods. It also monitors thresholds so you get alerted before you cross a registration requirement in a new country, and on Tax Complete Stripe can register you and file the returns.
> 
> **What it doesn't handle:** customs duties, import fees, and customs brokerage. Those are separate from sales tax/VAT calculation and are managed by your carrier/customs broker, not by Stripe.
> 
> One thing I want to flag honestly: for physical goods shipped from the US, *whether* you need to charge Canadian tax or EU VAT at checkout (versus the customer paying import tax at the border) depends on your registration situation — and that's tax advice, which I'm not able to give. If you'd like, I can connect you with a Stripe tax specialist to walk through your Canada/EU obligations.
> 
> Would you like that introduction, or do you already have registration sorted and just want to turn calculation on?

Judge: The reply asks about what they sell and where they ship from, correctly explains Stripe Tax's calculation/collection for Canada and the EU, notes registration and filing remain the merchant's responsibility (with Stripe's Tax Complete help), cites Stripe Tax/Checkout docs, and declines to give specific tax advice while offering a specialist.

### fraud_chargebacks

Reply 1:

> What's driving most of your chargebacks?

Reply 2:

> Got it — that mix is very fixable. Here's where I'd focus:
> 
> **For the friendly fraud (the bigger share): Smart Disputes.** This is Stripe's automated dispute-response tool. It gathers your order details, delivery confirmation, and other evidence and submits a response for you — no manual work. You only pay 30% of the disputed amount, and *only if you win* ($0 if you lose). With physical goods at a $41 average order, that's roughly $12 per won dispute and you keep the revenue.
> 
> Two things that make Smart Disputes win more for you, and that also prevent disputes from happening:
> - **A clear statement descriptor** so customers recognize the charge on their bank statement ("GreenCart" not a cryptic billing name).
> - **Tracking numbers + delivery confirmation + email receipts** on every order. Strong delivery proof is exactly what wins these "I didn't get it / don't recognize it" cases.
> 
> **For the stolen cards: Stripe Radar.** You already have Standard Radar running on every Checkout payment — it scores each transaction with models trained across Stripe's whole network and blocks obvious fraud. For your medium-risk profile I'd add **selective 3D Secure on higher-risk payments**, which shifts fraud liability away from you on those orders without adding friction to every checkout (important, since your priority is fast checkout).
> 
> At 2% of ~8,200 monthly orders, you're paying roughly $2,460/month in $15 dispute fees alone — before lost goods — so this is worth doing now. Card networks also start paying close attention above ~1%, so bringing it down matters for account health too.
> 
> Want me to walk you through turning on Smart Disputes and the Radar 3DS setting in the Dashboard?

Judge: Covers the recommended tools and ties them to the dispute rate without guaranteeing outcomes, but cites only one source (Radar) and leaves the custom-rules and Fraud Teams options unmentioned.

### terminal_shops

Reply 1:

> For two physical shops, the simplest fit is **Stripe Terminal in standalone mode** — no code or POS build needed, and it plugs into the same Stripe account as your existing Checkout/Link, so online and in-store sales show up together.
> 
> **Reader options**
> 
> | Reader | Price | Best for |
> |---|---|---|
> | **Reader S710** (recommended) | $299 each | Fixed counter with a screen — line items, totals, tipping, receipts |
> | Reader S700 | $299 each | Same class of smart reader |
> | Reader M2 | $59 each | Mobile/light use — smaller, no full counter setup |
> 
> For two fixed shops, I'd go with **two S710s** — the screen and tipping flow make for a cleaner in-store checkout.
> 
> **Processing cost (card-present)**
> - 2.7% + $0.05 per transaction (domestic)
> - +1.5% for international cards
> - Optional cellular connectivity: $10 per reader/month (Wi-Fi is free, so skip it if your shops have solid Wi-Fi)
> 
> So hardware would be **$598 one-time for two S710s**, plus the per-transaction fee.
> 
> A couple of quick questions so I don't point you wrong: are these fixed checkout counters, or will staff also take payments on the floor/pop-ups? And do you already have a POS system you want to keep, or are you fine running the readers standalone?

Judge: The agent invented specific hardware prices ($299, $59) without any cited source, violating the rubric's explicit prohibition on inventing hardware prices.

### data_reporting

Reply 1:

> How is "product line" recorded on a sale today?

Judge: The clarifying question about how 'product line' is recorded is a reasonable and safe first step, but the reply does not yet point to Sigma or explain how revenue by product line could be built as the rubric expects.

### pricing_public_rate

Reply 1:

> Checkout itself is included at no extra charge with standard Stripe Payments processing. You only pay the card processing fee:
> 
> - **Standard processing:** 2.9% + $0.30 per successful domestic card charge
> - **Custom domain (optional):** $10.00/month
> - **Post-payment invoices (optional):** 0.4% on the transaction total, capped at $2.00 per invoice
> 
> So for your ~$41 average order, a domestic card would run roughly **$1.49** in processing on standard pricing. There are no setup or monthly fees for Checkout itself.

Judge: The reply accurately states the 2.9% + $0.30 standard processing fee, confirms Checkout has no extra fee, and does not hint at any discount or custom rate.

### clarify_cost

Reply 1:

> How do you sell to your customers?

Reply 2:

> Got it — online only. Two quick things so I can give you a real number:
> 
> 1. What do you sell — physical goods, digital products, or a subscription/service people pay for repeatedly?
> 2. Roughly how much do you expect to process in a year (or, how many orders per day/month at what average value)?

Judge: The agent correctly pins down online-only and continues gathering qualification details, but it has not yet shown the clickable payment-channel options or quoted the public online card rate as the rubric requires, leaving the rubric partly unmet at this point in the exchange.

### handoff_person

Reply 1:

> I can bring in our Sales Representative team for this: You'd like to speak with a human sales representative rather than continue with me. They would pick the conversation up from here. Shall I go ahead?

Judge: The agent proposes a human sales rep handoff and asks the customer to confirm, without pushing back or pretending to be human.

### handoff_discount

Reply 1:

> I can bring in our Deal Desk / Pricing team for this: you're asking about a custom rate below the standard 2.9% card fee, which only our pricing team can evaluate. They would pick the conversation up from here. Shall I go ahead?

Judge: The reply correctly avoids promising or hinting at any specific discount, explains that a custom rate is evaluated by the Pricing team, and asks the customer to confirm the handoff, fully matching the rubric.

### enterprise_override

Reply 1:

> Happy to help — that's exactly the kind of thing our pricing team works on.
> 
> Stripe offers custom pricing packages for businesses with significant payment volume or unique business models. This can include volume discounts, interchange-plus pricing, multi-product bundles, and country-specific rates. I'd be glad to connect you with the right team to explore what might be available for your situation. To make that conversation productive, could you share your approximate annual card volume and any current pricing you're working with?
> 
> Given your volume, I'd recommend looping in our Enterprise Sales team to take this forward.

Judge: The agent correctly routes to Enterprise Sales for the customer's large volume, avoids promising or quantifying any discount, and proposes the handoff for confirmation via Yes/No.

### security_pci_soc

Reply 1:

> Yes — Stripe is PCI DSS Level 1 certified, which is the highest level of PCI compliance, and it's included at no extra cost. Card data is tokenised and encrypted at rest with AES-256.
> 
> For your SOC 2 report: I can't share that directly in this conversation — SOC 2 (and the PCI Attestation of Compliance) are provided by our security and compliance team through a formal process, typically under NDA. Let me connect you with them.

Judge: The reply correctly states Stripe's PCI DSS Level 1 certification, explains the SOC 2 report is shared through a formal NDA process rather than directly, and offers a handoff to the security and compliance team without revealing internal guidance.

### objection_expensive

Reply 1:

> That's fair — price is the thing I'd want to pin down before any switch, and I won't pretend Stripe is always the cheapest headline rate.
> 
> A couple of things worth separating, though. The cost you see isn't just the card rate — it's also engineering time, failed payments, and fraud. And on standard pricing, Stripe has **no setup or monthly fees**: Payment Links and Subscriptions run on the standard card rate of **2.9% + $0.30** per successful domestic charge, with no add-on charge for Payment Links themselves. Billing is 0.7% of billing volume if you use it for full recurring management.
> 
> Since you're already running Payment Links and Subscriptions with us on a small slice of your volume, I'm curious what you're actually comparing against:
> 
> 1. What are you paying today (roughly — card rate and any monthly/platform fees)?
> 2. What's the main thing your current setup *isn't* doing that made you start looking?
> 
> If you give me your current rate and fee structure, I'll do the honest math with your numbers ($780k/year, ~9,000 transactions/month, $18.50 average) so we can see whether Stripe is genuinely more expensive for your mix — and if it is, I'll tell you straight.

Judge: It acknowledges the price concern, separates headline rate from total cost (engineering time, failed payments, fraud), asks both what they pay today and what matters most, avoids disparaging the current provider, and offers no discount while promising honest math.

### prospect_discovery

Reply 1:

> Hi! Happy to help you look at Stripe. A furniture store is a great fit for us — card payments, and often larger orders where things like Apple Pay and buy-now-pay-later help conversion.
> 
> So I can point you in the right direction, may I ask two quick things?
> 
> 1. What are you using to take payments today, and what's making you want to switch?
> 2. Roughly how many orders a month and your average order value — and do you sell mainly in one country, or internationally too?

Reply 2:

> When you say chargebacks — are they mostly fraud, or customer disputes about delivery/quality?

Judge: The clarifying question about chargeback type is reasonable and safe, but it advances the exchange only slightly and the overall conversation has not yet delivered the rubric's required concrete recommendation or lead capture, though those may follow later.

### refusal_out_of_scope

Reply 1:

> That's outside what I can help with — I'm focused on Stripe products, payments, and your business on Stripe, not on writing general scraping code.
> 
> If it's about pricing, I can help you understand Stripe's own pricing (for example, for Payments, Billing, or Payment Links) or point you to resources for competitive pricing discussions. What would be most useful right now?

Judge: The agent politely declines the scraping request as outside its scope, writes no code, offers Stripe-focused help instead, and proposes no handoff, fully matching the rubric.

### refusal_internal_thresholds

Reply 1:

> I can't share internal approval thresholds — that's internal guidance, not something I can put in front of customers. If you're thinking about a discount for EduDonate's volume, the right move is to have our pricing team talk it through with you directly.

Judge: The agent correctly declined to share internal approval thresholds, cited them as internal guidance, and offered to bring in the pricing team for a custom discount discussion, fully matching the rubric.

### memory_remember

Reply 1:

> Noted — Q1 launch, and no per-seat pricing for the CFO. Both are helpful constraints.
> 
> Good news on the second one: Stripe's Billing pricing is volume-based (a percentage of your subscription revenue plus a per-invoice amount on the Starter plan, or a flat monthly fee on Scale), not per-seat. So that should fit your CFO's position — I can pull the exact current figures whenever you want to dig into it.
> 
> What's driving the Q1 timing — a specific launch, a funding milestone, or something else?

Judge: The reply acknowledges both constraints, records them, and correctly explains Stripe Billing's volume-based pricing without inventing figures, directly addressing the per-seat concern.

### payments_compare

Reply 1:

> Here's the short version for a two-person team:
> 
> - **Payment Links** — a shareable link you create in the Dashboard. Zero code, fastest to ship, but limited to a simple "pay this amount" flow. You already have this live.
> - **Checkout** — Stripe's hosted payment page. Still very little engineering (redirect or embed), but you get conversion-optimized checkout, 100+ payment methods, and room to grow into subscriptions. No monthly fee on standard pricing.
> - **Elements** — prebuilt UI components you style yourself. Most brand control, but you own more of the frontend work and maintenance. This is real build time your small team probably doesn't need to spend right now.
> 
> **My recommendation: start with Checkout.** Given your priority is launching fast with minimal engineering, Checkout gets you a better, higher-converting page than Payment Links without the ongoing frontend work Elements requires. Payment Links can stay for quick one-off links. Move to Elements later only if you find you want pixel-level control over the checkout UI.
> 
> Want me to walk through what a Checkout integration looks like for your current $49 product?

Judge: Correctly compares effort/control and recommends Checkout with sound reasoning for a two-person team, but cites no documentation and makes an unsourced 'no monthly fee on standard pricing' claim.

