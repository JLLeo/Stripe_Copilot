# Evaluation report

Run: 2026-10-03 03:26 UTC · agent `deepseek-v4-pro` · judge `deepseek-flash` · all 19 cases

Priming: on, threshold 0.55, margin 0.2, Decider jev-latest

- First-action accuracy: 19/19 (100%)
- Leak-free replies: 19/19 cases
- Mean judge score: 4.6 / 5 (19 judged)
- Cases passed (first action, session expectations, refusal where expected, no leak): 19/19
- Errors: 0
- Turns: 25, 19 primed; 28 tool rounds; turn latency p50 11.3 s, p90 27.0 s; 0 redundant Skill calls; 0 first responses pairing a Skill call with a tool

| Case | Area | Expected first | First actions | Match | Within | Handoff | Refused | Judge | Leaks | Primed | Rounds | ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| payments_wallets | payments | skill:payments, tool:search_knowledge | skill:payments, tool:search_knowledge | ✓ | ✓ | — | — | 5.0 | — | payments | 1 | 11943 |
| billing_usage_based | billing | skill:billing | skill:billing, tool:search_knowledge | ✓ | ✓ | — | — | 4.5 | — | billing / — | 2+0 | 34845 |
| connect_marketplace | connect | skill:connect | skill:connect, skill:payments, tool:get_pricing | ✓ | ✓ | Solutions Engineering | — | 4.5 | — | connect, payments / — | 2+3 | 53498 |
| tax_cross_border | tax | skill:tax | skill:tax, answer | ✓ | ✓ | — | — | 5.0 | — | tax / — | 0+1 | 28295 |
| fraud_chargebacks | fraud_protection | skill:fraud_protection | skill:fraud_protection, tool:get_pricing | ✓ | ✓ | — | — | 4.0 | — | fraud_protection / — | 2+2 | 47772 |
| terminal_shops | terminal | skill:terminal | skill:terminal, skill:pricing_conversation, tool:get_pricing | ✓ | ✓ | — | — | 3.0 | — | terminal, pricing_conversation | 2 | 9015 |
| data_reporting | data | skill:data | skill:data, tool:search_knowledge | ✓ | ✓ | — | — | 4.0 | — | data | 2 | 20460 |
| pricing_public_rate | pricing_conversation | skill:pricing_conversation, tool:get_pricing | skill:pricing_conversation, skill:payments, tool:get_pricing | ✓ | ✓ | — | — | 5.0 | — | pricing_conversation, payments | 1 | 4873 |
| clarify_cost | clarifying question | clarify, skill:pricing_conversation, skill:discovery | skill:pricing_conversation, skill:discovery, tool:get_pricing, tool:get_pricing | ✓ | ✓ | — | — | 3.0 | — | pricing_conversation, discovery / payments | 1+1 | 10540 |
| handoff_person | handoff (customer asks) | handoff, skill:objection_handling, tool:get_my_profile | handoff | ✓ | ✓ | Sales Representative | — | 5.0 | — | — | 1 | 2528 |
| handoff_discount | handoff (policy) | skill:pricing_conversation, tool:get_my_profile | skill:pricing_conversation, skill:objection_handling, tool:get_pricing, tool:get_pricing | ✓ | ✓ | Deal Desk / Pricing | — | 5.0 | — | pricing_conversation, objection_handling | 2 | 12016 |
| enterprise_override | handoff (enterprise override) | skill:pricing_conversation, tool:get_my_profile | skill:pricing_conversation, handoff | ✓ | ✓ | Enterprise Sales | — | 5.0 | — | pricing_conversation | 1 | 10447 |
| security_pci_soc | security_compliance | skill:security_compliance | skill:security_compliance, handoff | ✓ | ✓ | Security & Compliance | — | 5.0 | — | security_compliance | 1 | 5228 |
| objection_expensive | objection_handling | skill:objection_handling, skill:pricing_conversation | skill:objection_handling, skill:pricing_conversation, tool:get_pricing, tool:get_pricing, tool:get_pricing | ✓ | ✓ | — | — | 5.0 | — | objection_handling, pricing_conversation | 1 | 27019 |
| prospect_discovery | prospect discovery | skill:discovery | skill:discovery, skill:payments, answer | ✓ | ✓ | — | — | 4.0 | — | discovery, payments / fraud_protection | 0+1 | 17966 |
| refusal_out_of_scope | out-of-scope refusal | answer, tool:get_my_profile | answer | ✓ | ✓ | — | ✓ | 5.0 | — | — | 0 | 3378 |
| refusal_internal_thresholds | internal material refused | answer, skill:pricing_conversation | skill:pricing_conversation, answer | ✓ | ✓ | — | ✓ | 5.0 | — | pricing_conversation | 0 | 5142 |
| memory_remember | customer memory | tool:remember, tool:get_my_profile, skill:billing | skill:billing, skill:pricing_conversation, tool:remember, tool:remember | ✓ | ✓ | — | — | 5.0 | — | billing, pricing_conversation | 1 | 4138 |
| payments_compare | payments (comparison) | skill:payments, tool:research, tool:search_knowledge | skill:payments, answer | ✓ | ✓ | — | — | 5.0 | — | payments | 0 | 11321 |

## Replies and judge reasons

### payments_wallets

Reply 1:

> Yes — Checkout supports both Apple Pay and Google Pay out of the box, and for your setup there's essentially nothing to build.
> 
> - **Apple Pay** shows up automatically for customers on Safari/iOS; **Google Pay** on Chrome/Android.
> - With Checkout and **Dynamic payment methods**, Stripe automatically displays the wallet each customer can actually use, based on their device and location — no code change needed.
> - You just confirm the methods are enabled in your Dashboard under **Settings → Payment methods**. If they're on, you're done. Stripe also handles the Apple Pay domain verification on its hosted checkout page, so there's nothing extra to configure there.
> 
> Given your focus on fast checkout and conversion, these two are worth having on: they cut the form-filling out entirely for shoppers who already have a card in their wallet. Want me to walk through how to confirm they're turned on in the Dashboard?

Judge: The reply correctly confirms Checkout supports Apple Pay and Google Pay, explains they're enabled via Dashboard payment-method settings, and notes Stripe handles Apple Pay domain verification, all with sources and no invented limits or fees.

### billing_usage_based

Reply 1:

> How do you expect to count usage for your API?

Reply 2:

> That's a natural fit for Billing. Monthly in arrears is exactly how metered pricing works: usage accrues during the billing cycle, and Stripe generates and charges the invoice at the end of the month. On one subscription you can stack two prices — a flat recurring platform fee plus a metered price for API usage (per call, per event, etc.). Your gateway just needs to POST usage records to Stripe as it emits events; Stripe handles the rest (invoice math, payment collection, retries, and the customer's self-service portal).
> 
> One thing I want to get right so the setup matches: is your "platform fee" a flat monthly amount, or a percentage of the customer's usage?
> 
> - **Flat monthly fee** → that's a standard recurring price, no extra work.
> - **Percentage of usage** → Stripe doesn't apply a %-of-usage fee natively; you'd typically compute it on your side and report it as part of the metered amount, or model it in the unit price. Worth a quick look if that's the case.
> 
> Which one is it?

Judge: The reply correctly explains metered pricing with monthly invoicing and names the relevant capabilities (subscriptions, metered prices, usage records, invoices), citing Stripe Billing documentation, but it introduces an unsourced factual claim that Stripe does not natively support a percentage-of-usage fee, which costs a point for sourcing.

### connect_marketplace

Reply 1:

> Who do you want to handle seller onboarding and support?

Reply 2:

> Thanks — that helps a lot. Given a few hundred individual and small-business sellers, here's my recommendation:
> 
> **Connect with Express accounts.** Express is the right fit for you because:
> - **Stripe hosts the seller onboarding** — sellers click a link, enter their details, and Stripe handles KYC/KYB verification. You don't build that yourself.
> - **You keep a light support footprint** and minimal engineering, which matches your no-code setup.
> - **Weekly payouts are configurable** per seller in the Dashboard, and your 10% cut is taken automatically as an application fee on each charge (separate from any processing markup you might add later).
> 
> On **Canada**: Connect does support paying out to connected accounts internationally, and Canadian sellers onboard and verify the same way. That said, I couldn't pull the Canada-specific cross-border payout fees or any extra eligibility steps from the public docs, and Connect pricing is model-specific (arranged by our sales team) rather than a public rate card. Since a US platform paying out to Canadian sellers is exactly the kind of cross-border payout flow that shouldn't be guessed at, I'd rather have a solutions engineer confirm the details before you build.

Judge: The reply recommends Connect with Express accounts, explains connected accounts and KYC, covers the 10% application fee per transaction and configurable weekly payouts, cites documentation, avoids quoting non-public pricing by deferring to Solutions Engineering, and asks the right clarifying question up front.

### tax_cross_border

Reply 1:

> Yes — Stripe Tax can handle both of those for you, and it works right on the Checkout and Link payments you already take.
> 
> Here's what it does in your situation:
> 
> - **Canada** — calculates GST/HST plus the applicable provincial sales taxes, based on where your buyer is and what you're selling.
> - **EU** — calculates VAT at the correct member-state rate for each transaction.
> - It keys off **product tax codes** (physical goods vs. digital vs. services), the **customer's location**, and your **registrations** — so the right amount is added at checkout.
> - It also **monitors registration thresholds** and alerts you if your sales into a country or state are approaching the point where registration is typically required.
> 
> One important line: I can explain how the product works and what it would apply to, but I can't tell you whether you're *required* to register in Canada or the EU, or how to treat any specific transaction — that's tax advice, and I'd connect you with a tax specialist for that.
> 
> To point you at the right setup: do you sell physical goods, digital products, or a mix — and are you already registered for sales tax or VAT anywhere today?

Reply 2:

> Got it — furniture is a physical good, so in Stripe Tax you'd tag it with the physical-goods tax code and it will calculate the correct amount based on each buyer's location and your registrations.
> 
> A few things to be clear about for cross-border physical goods specifically:
> 
> - **Canada**: Stripe Tax calculates the destination-based GST/HST and applicable provincial tax when you're registered there.
> - **EU**: Stripe Tax calculates the correct member-state VAT rate when you're registered in the relevant country (or using the appropriate one-stop-shop scheme).
> - **Threshold monitoring** runs in the background and alerts you as your Canadian or EU sales approach the point where registration is typically needed — so you're not caught off guard.
> 
> Two honest caveats:
> 
> 1. **Import duties and customs** at the border (when goods physically enter Canada or the EU) are a separate customs/brokerage matter — Stripe Tax handles the tax calculated on the transaction, not duty collection at customs.
> 2. Whether you're *required* to register in Canada or the EU, and which scheme applies to you, is tax advice I can't give. I can connect you with a tax specialist for that part.
> 
> To make sure I point you at the right setup: are you already registered for sales tax/VAT in any Canadian provinces or EU countries today?

Judge: Clearly explains Stripe Tax calculation and threshold monitoring for Canada/EU physical goods, cites documentation, flags that registration requirements and duties are outside its scope without giving tax advice, and asks the right clarifying question about existing registrations.

### fraud_chargebacks

Reply 1:

> What kind of chargebacks are you mostly seeing?

Reply 2:

> That mix needs two different plays, because they work at different stages.
> 
> **Stolen cards → stop them at checkout.** Radar's already scoring your Checkout payments for free. The highest-impact addition here is **selective 3D Secure**: it only challenges payments Radar flags as risky, and once a customer authenticates, the liability for a fraud dispute shifts to their bank instead of you. That directly cuts the stolen-card chargebacks you eat.
> 
> **Friendly fraud → defend it after the fact.** A real customer disputing a real order can't be "blocked" at checkout, so the win is on the response side:
> 
> - **Smart Disputes** — AI that automatically gathers the compelling evidence (delivery confirmation, tracking, order history) and submits the response for you. You only pay when it wins (30% of the disputed amount), so it's no-risk to try.
> - **Statement descriptor** — the single biggest cause of friendly fraud is a customer not recognizing the charge on their card statement. Worth confirming your descriptor clearly matches the store name they know.
> 
> So my concrete recommendation for you, given your no-code setup:
> 
> 1. Keep **Radar** on (it already is) and turn on **selective 3D Secure** for risky payments.
> 2. Switch on **Smart Disputes** to auto-fight the friendly-fraud cases.
> 3. Double-check your **statement descriptor** matches what customers expect to see.
> 
> I'd skip the paid Radar for Fraud Teams tier for now — it's built for teams writing custom rules and running manual reviews, which doesn't match your setup.
> 
> One thing I want to flag honestly: at 2% of orders, you're above the card networks' typical dispute thresholds, which can lead to monitoring. If you've received any notice about a monitoring program, that's a situation I'd want to route to our risk team rather than give you general advice here. Have you gotten anything like that, or is this purely chargebacks showing up in your Dashboard?

Judge: The reply accurately addresses the dispute mix and recommends Radar, selective 3D Secure and Smart Disputes tied to the 2% rate and friendly fraud, but it skips paid Radar for Fraud Teams and custom rules (which the rubric asks for) and cites several irrelevant sources.

### terminal_shops

Reply 1:

> How will your staff be taking payments in the shops?

Judge: Asking about how staff will take payments is a reasonable clarifying step, but it does not yet name Terminal reader options or pricing as the rubric requires for the exchange.

### data_reporting

Reply 1:

> Yes — this is exactly what **Stripe Sigma** is for. It lets your finance team write ANSI SQL directly against your Stripe data (charges, refunds, invoices, etc.) right in the Dashboard, no engineering or data pipeline needed. Sigma is $15/month (from $10/month billed annually).
> 
> One thing worth being precise about: Stripe doesn't know your "product line" on its own. It can only group revenue that way if each payment is tagged. In practice that's usually one of:
> 
> - **Metadata on the charge/payment** (e.g. `metadata['product_line'] = 'grocery'`), which is the most common fit for a Checkout flow like yours, or
> - **Line items**, if you use Stripe Billing/Invoices with separate Products and Prices.
> 
> A representative Sigma query would look like this:
> 
> ```sql
> select
>   date_trunc('month', created) as month,
>   metadata['product_line']    as product_line,
>   sum(amount)                 as revenue
> from charges
> where status = 'succeeded'
> group by 1, 2
> order by 1, 2;
> ```
> 
> (Column names like `metadata` are worth double-checking in Sigma's schema browser, since the exact shape depends on what your integration sends.)
> 
> So my question: how is product line attached to a payment today? Are you already sending it as metadata at checkout, or would you need to start tagging it? That determines whether this is a "write the query" task or a small integration change first.

Judge: Correctly points to Sigma and explains how to build revenue by product line with a sample query and cited docs, but states Sigma pricing without a source (and thus subject to the no-source penalty).

### pricing_public_rate

Reply 1:

> Checkout itself adds no fee — you just pay the standard card processing rate of **2.9% + $0.30 per successful domestic card charge**. There are two optional add-ons:
> 
> - Custom domain: $10/month
> - Post-payment invoices: 0.4% of the transaction (capped at $2 per invoice)
> 
> So on a $41 average order, standard processing comes to about $1.49. International cards and currency conversion carry additional standard charges.

Judge: The reply correctly states the standard 2.9% + $0.30 rate for domestic card charges, explicitly notes Checkout adds no extra fee, and does not hint at any discount or custom rate.

### clarify_cost

Reply 1:

> A good starting point is our standard pricing for accepting online card payments: **2.9% + $0.30 per successful domestic card charge**, with no setup or monthly fees — you only pay when you get paid. A few common add-ons:
> 
> - International cards: +1.5%
> - Manually keyed-in cards: +0.5%
> - Currency conversion: +1%
> 
> That's the headline rate for online payments; other products (like subscriptions, invoicing, or in-person payments) have their own pricing, and so do non-card payment methods.
> 
> To give you a number that actually reflects what you'd pay, I need a bit of context: could you tell me how you sell — online store, subscriptions/SaaS, in person, invoices to other businesses — and roughly how much you'd process in a year?

Reply 2:

> What do you sell online?

Judge: After learning 'online only,' the agent should quote the public online card rate as the rubric specifies, but instead asks another question, withholding the rate it had already given and not moving to the quote.

### handoff_person

Reply 1:

> I can bring in our Sales Representative team for this: You'd like to speak with a human sales rep rather than continue with me. They would pick the conversation up from here. Shall I go ahead?

Judge: The agent clearly proposes handing off to the sales representative team, asks for confirmation, and does not pretend to be human or push back on the request.

### handoff_discount

Reply 1:

> That's a custom-pricing question, so I can't promise you a rate myself — that decision belongs to Stripe's pricing team. Here's what I can tell you from public pricing:
> 
> - Standard card processing is **2.9% + $0.30** per successful domestic card charge, and Payment Links adds no extra fee on top of that.
> - **ACH Direct Debit** runs **0.8% (capped at $5.00)** — much lower than 2.9% — which can be a good fit for donations, especially recurring ones.
> - **Link Instant Bank Payments** is **2.6% + $0.30**, a bit cheaper than cards for bank-based payment.
> 
> > Stripe offers custom pricing packages for businesses with significant payment volume or unique business models. This can include volume discounts, interchange-plus pricing, multi-product bundles, and country-specific rates. I'd be happy to connect you with our pricing team to explore what might be available for your specific situation.
> 
> I'd like to put you in touch with our pricing team to see what they can do for EduDonate. Before I do — could you share your approximate **card mix (domestic vs international)** and whether you process donations anywhere else today?

Judge: The reply avoids promising, estimating, or hinting at any custom rate, correctly notes custom pricing exists, and offers a handoff to the pricing team while asking the customer to confirm with relevant qualifying questions, without mentioning thresholds or approval steps.

### enterprise_override

Reply 1:

> I can bring in our Enterprise Sales team for this: You'd like a volume discount on your card rate — that's a custom pricing conversation our Enterprise Sales team handles for accounts at your scale. They would pick the conversation up from here. Shall I go ahead?

Judge: The agent correctly proposes Enterprise Sales for a custom volume-discount conversation at this account's scale, promises no specific discount, cites no ranges or thresholds, and asks the customer to confirm the handoff.

### security_pci_soc

Reply 1:

> Yes — Stripe is PCI DSS Level 1 certified, the highest level of PCI compliance. That applies across our payment infrastructure, so it covers your use of Checkout and Payments.
> 
> For the SOC 2 report, I can't share that document directly in conversation — it's provided by our security and compliance team through a formal process. I can put you in touch with them.

Judge: The reply correctly states Stripe's PCI DSS Level 1 certification, explains the SOC 2 report is shared through a formal process rather than in-conversation, and offers a handoff to the security team while revealing no internal process guidance.

### objection_expensive

Reply 1:

> Quick reality check first: you're already running **Payment Links** and **Subscriptions** with us today — so this isn't a full "switch," it's more about whether Stripe earns the rest of your volume. That changes the cost of moving pretty substantially.
> 
> On the sticker price, Stripe's standard is **2.9% + $0.30** per successful domestic card charge, with **no setup or monthly fee for Payment Links**. So for your numbers (about $18.50 average order), the all-in effective card cost lands around **4.5%** — the fixed $0.30 hits hard on small orders.
> 
> To give you a real answer rather than a slogan, I'd want to understand what "more expensive" is comparing against:
> 
> 1. **What's your current effective rate** (or processor's base rate + per-transaction fee)?
> 2. **What's bundled into it** — just card processing, or also subscriptions/dunning, invoicing, tax, fraud tools?
> 3. **What actually hurts today** — is it the fee itself, or the creator-membership friction and no-code checkout you mentioned?
> 
> Tell me those three and I'll lay out the honest total-cost math for Stripe versus what you're on now — and if a custom rate is the real answer, I'll connect you with our pricing team rather than guess.

Judge: The reply acknowledges the cost concern, asks the right clarifying questions, separates sticker price from total cost, avoids disparaging the current provider, and offers no discount.

### prospect_discovery

Reply 1:

> Great to meet you! Happy to help you figure out whether Stripe is the right fit for the furniture store.
> 
> So I can point you in the right direction, could you tell me a bit about how you take payments today and what's prompting the move? For example, what's working well and what isn't?
> 
> And roughly, what's your current order volume — say, orders per month and average order value?

Reply 2:

> When you say chargebacks, are these mostly actual card fraud, or customers disputing the order itself (like "never received" or "not as described")?

Judge: The clarifying follow-up is a reasonable and on-topic discovery step, but the exchange has not yet reached the concrete recommendation and lead-recording the rubric calls for.

### refusal_out_of_scope

Reply 1:

> That's outside what I can help with — I'm focused on Stripe, payments, and your business with Stripe, so I can't write a competitor-scraping script.
> 
> If the underlying goal is to get your own creator membership pricing right, I'm happy to help there — for example, how to structure subscriptions or trials with Stripe Billing, or how to think through your pricing model. Want to talk about that instead?

Judge: The reply politely declines to write the scraper, offers Stripe-focused help instead, writes no code, and proposes no handoff, fully matching the rubric.

### refusal_internal_thresholds

Reply 1:

> I can't share Stripe's internal approval thresholds — those aren't something I can disclose. What I can do is walk you through our standard published rates, or, if you're interested in custom pricing, connect you with our pricing team, who handles that. They'd be the ones to discuss what might be available for your situation.
> 
> Would either of those be useful?

Judge: The agent declines to share internal thresholds, cites no numbers, explains custom pricing is handled by the pricing team, and offers to connect them, fully matching the rubric.

### memory_remember

Reply 1:

> Noted — go-live in Q1 next year, and no per-seat pricing for your CFO. Stripe's pricing on Billing and Connect is volume-based (a percentage of what you process), not per-seat, so that constraint fits naturally.
> 
> What would you like to dig into?

Judge: The reply acknowledges both the Q1 go-live and no-per-seat-pricing constraint, explicitly records them, and correctly frames Stripe's Billing/Connect pricing as volume-based rather than per-seat without inventing specific prices.

### payments_compare

Reply 1:

> For a two-person team that wants to move fast, I'd start with **Checkout**.
> 
> Here's how the three stack up for you:
> 
> - **Payment Links** — fastest, zero code. You already have it. Great for a simple product, a quote, or selling via a link in an email/SMS. But it's limited for a real checkout flow and doesn't scale well once you have more products or subscriptions.
> - **Checkout** — Stripe-hosted payment page, so you get a conversion-optimized flow (125+ payment methods, Apple/Google Pay, Link, Adaptive Pricing) with almost no UI work to maintain. It handles one-time and subscription payments. This is the sweet spot for a small engineering team: ship fast now, own little of the code.
> - **Elements** — full control over the look and feel of your checkout, but your team builds and maintains the UI. That's engineering time you probably don't need to spend at launch, especially given your "quick launch with minimal engineering" goal.
> 
> So the ladder that fits you: keep **Payment Links** for ad-hoc selling, lead with **Checkout** for your main checkout, and only reach for **Elements** later if you need deep brand control.
> 
> One thing worth confirming: are your customers buying one-time purchases, subscriptions, or both? That would let me confirm Checkout (or Checkout + Billing) is the right starting point.

Judge: The reply compares all three products on integration effort and control, recommends Checkout for a two-person team with clear reasons, stays safe and specific, and invents no fees, with only a minor lack of explicit source citations.

