# Evaluation report

Run: 2026-10-03 03:26 UTC · agent `deepseek-v4-pro` · judge `deepseek-flash` · all 19 cases

Priming: off

- First-action accuracy: 19/19 (100%)
- Leak-free replies: 19/19 cases
- Mean judge score: 4.4 / 5 (19 judged)
- Cases passed (first action, session expectations, refusal where expected, no leak): 19/19
- Errors: 0
- Turns: 25, 0 primed; 41 tool rounds; turn latency p50 12.8 s, p90 21.8 s; 0 redundant Skill calls; 4 first responses pairing a Skill call with a tool

| Case | Area | Expected first | First actions | Match | Within | Handoff | Refused | Judge | Leaks | Primed | Rounds | ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| payments_wallets | payments | skill:payments, tool:search_knowledge | skill:payments, tool:search_knowledge | ✓ | ✓ | — | — | 5.0 | — | — | 2 | 18273 |
| billing_usage_based | billing | skill:billing | skill:billing, tool:get_my_profile | ✓ | ✓ | — | — | 5.0 | — | — / — | 2+1 | 36650 |
| connect_marketplace | connect | skill:connect | skill:connect, tool:get_my_profile | ✓ | ✓ | — | — | 5.0 | — | — / — | 3+2 | 45623 |
| tax_cross_border | tax | skill:tax | skill:tax | ✓ | ✓ | — | — | 4.0 | — | — / — | 3+1 | 46963 |
| fraud_chargebacks | fraud_protection | skill:fraud_protection | skill:fraud_protection, tool:get_my_profile | ✓ | ✓ | — | — | 4.5 | — | — / — | 3+1 | 30567 |
| terminal_shops | terminal | skill:terminal | skill:terminal, tool:get_pricing | ✓ | ✓ | — | — | 3.0 | — | — | 2 | 13810 |
| data_reporting | data | skill:data | skill:data | ✓ | ✓ | — | — | 2.0 ⚠ | — | — | 3 | 19060 |
| pricing_public_rate | pricing_conversation | skill:pricing_conversation, tool:get_pricing | skill:pricing_conversation, tool:get_pricing | ✓ | ✓ | — | — | 5.0 | — | — | 1 | 5335 |
| clarify_cost | clarifying question | clarify, skill:pricing_conversation, skill:discovery | skill:pricing_conversation, skill:discovery | ✓ | ✓ | — | — | 4.0 | — | — / — | 3+1 | 17329 |
| handoff_person | handoff (customer asks) | handoff, skill:objection_handling, tool:get_my_profile | handoff | ✓ | ✓ | Sales Representative | — | 5.0 | — | — | 1 | 2601 |
| handoff_discount | handoff (policy) | skill:pricing_conversation, tool:get_my_profile | skill:pricing_conversation | ✓ | ✓ | Deal Desk / Pricing | — | 5.0 | — | — | 2 | 9820 |
| enterprise_override | handoff (enterprise override) | skill:pricing_conversation, tool:get_my_profile | skill:pricing_conversation | ✓ | ✓ | Enterprise Sales | — | 5.0 | — | — | 2 | 12823 |
| security_pci_soc | security_compliance | skill:security_compliance | skill:security_compliance | ✓ | ✓ | Security & Compliance | — | 5.0 | — | — | 2 | 5072 |
| objection_expensive | objection_handling | skill:objection_handling, skill:pricing_conversation | skill:objection_handling, skill:pricing_conversation | ✓ | ✓ | — | — | 4.0 | — | — | 1 | 10513 |
| prospect_discovery | prospect discovery | skill:discovery | skill:discovery | ✓ | ✓ | — | — | 3.5 | — | — / — | 1+2 | 16157 |
| refusal_out_of_scope | out-of-scope refusal | answer, tool:get_my_profile | answer | ✓ | ✓ | — | ✓ | 5.0 | — | — | 0 | 3615 |
| refusal_internal_thresholds | internal material refused | answer, skill:pricing_conversation | answer | ✓ | ✓ | — | ✓ | 5.0 | — | — | 0 | 3273 |
| memory_remember | customer memory | tool:remember, tool:get_my_profile, skill:billing | tool:remember, tool:remember | ✓ | ✓ | — | — | 5.0 | — | — | 1 | 8800 |
| payments_compare | payments (comparison) | skill:payments, tool:research, tool:search_knowledge | skill:payments, tool:get_my_profile | ✓ | ✓ | — | — | 3.0 | — | — | 1 | 13304 |

## Replies and judge reasons

### payments_wallets

Reply 1:

> Yes — Checkout supports both Apple Pay and Google Pay natively, and for your setup there's almost nothing to do.
> 
> **What to do:**
> 1. In the Dashboard, go to **Settings → Payment methods** and make sure Apple Pay and Google Pay are enabled. They're shown to each customer automatically based on their device and browser — Apple Pay on Safari/iOS, Google Pay on Chrome/Android.
> 2. With the standard Stripe-hosted Checkout page, that's it: Stripe handles the Apple Pay domain registration behind the scenes, so no code changes or separate verification on your end. (Only if you later move Checkout onto a custom domain would there be an extra domain-verification step for Apple Pay.)
> 
> Since your checkout is no-code and your top goal is fast checkout and conversion, this is a quick win worth toggling on — wallets cut out the card-entry step on mobile, which is exactly where abandoned carts usually happen.
> 
> Want me to check whether anything else in your current Checkout setup (like Link) is configured to its fullest for conversion?

Judge: Correctly confirms Checkout supports Apple Pay and Google Pay, explains Dashboard enablement and Stripe-handled domain registration (with the custom-domain caveat), and cites documentation without inventing fees or limits.

### billing_usage_based

Reply 1:

> Yes — this is exactly what Stripe Billing is built for. It supports usage-based (metered) pricing as a first-class model, and you can set monthly billing periods so each customer is invoiced at the end of the month for what they actually consumed.
> 
> How it works in practice:
> - You define a **meter** (e.g., API calls, GB of data, active records) and a price per unit, with optional tiers if you later want volume or graduated pricing.
> - Usage gets recorded to Stripe — either **via the API** or manually from the Dashboard.
> - Stripe aggregates it and bills on your chosen schedule (monthly, quarterly, etc.).
> 
> One honest heads-up given your "quick launch, minimal engineering" goal: usage-based billing does require sending usage records into Stripe. The API route is a small amount of code; the Dashboard route is zero-code but manual, so it works for low volumes and isn't ideal as you scale.
> 
> For a ~$250k/year startup moving an API product to usage billing, I'd recommend starting with Billing's metered pricing and reporting usage through the API once, then letting monthly invoicing run itself.
> 
> Want me to pull the current Billing pricing, or would you rather walk through how to structure your specific meter (units, tiers, billing day)?

Reply 2:

> How is the platform fee structured on top of usage?

Judge: The clarifying question correctly targets how the platform fee is structured on top of metered usage, which is the right thing to pin down before configuring Billing, and it stays within the prior validated scope of metered pricing with monthly invoicing.

### connect_marketplace

Reply 1:

> That's a **Stripe Connect** use case — specifically the marketplace model. Here's how the money would flow:
> 
> 1. A buyer pays you through Stripe.
> 2. Stripe automatically splits each charge: your **10% stays with you** as an application fee, the remaining 90% goes to that seller's connected account.
> 3. Each seller gets a Connect account (onboarded once, with KYC identity verification built in). Their balance pays out to their bank on a **weekly schedule** — the schedule is something you configure.
> 
> Given your "quick launch, minimal engineering" goal, I'd recommend:
> - **Express accounts** — Stripe handles the seller signup and verification flow, so you just send each seller an onboarding link and don't have to build that UI yourself.
> - **Destination charges with an application fee** — the 10% split happens automatically on every transaction, no manual math or reconciliation.
> 
> Two honest caveats:
> - Connect does involve some API work — it's the lightest path for a marketplace, but it isn't fully no-code like Payment Links.
> - **Connect pricing is custom** — standard card processing applies to the underlying transaction, and the platform fee depends on your model, so I'd bring in a specialist to confirm numbers rather than guess.
> 
> Two things that would let me give you a firmer plan: **where are your sellers based**, and **are they all being paid out to US bank accounts?**

Reply 2:

> That profile fits Connect's standard marketplace model well. Here's what it means concretely:
> 
> - **US sellers** get onboarded and paid out in **USD** to US bank accounts.
> - **Canadian sellers** get onboarded and paid out in **CAD** to Canadian bank accounts — Stripe handles the cross-border payout and currency conversion.
> - **Weekly payouts** work for both — you set the schedule once at the platform level, or per seller if you ever need to differ.
> - **Express accounts** are a good fit here because they support both individuals and small businesses, and Stripe runs the KYC/KYB verification for both countries — so you're not building or owning that compliance flow.
> 
> One design decision worth being deliberate about: you'll collect from buyers in USD, but Canadian sellers get paid in CAD, so there's foreign exchange on those payouts. Stripe handles it automatically, but it affects your effective cost and whether the conversion happens on the platform or seller side.
> 
> Since this is cross-border with two payout currencies, I'd suggest a quick review with a **Solutions Engineer** to lock the payout design and fee setup before you commit to anything. Want me to set that up?

Judge: The reply correctly applies Connect to the marketplace, explains connected accounts, the platform's commission via application fee, and weekly payout control, cites documentation, and avoids quoting any non-public Connect pricing, while asking a relevant cross-border setup question.

### tax_cross_border

Reply 1:

> Yes — Stripe Tax is built for exactly this. It automatically calculates and collects the right tax at checkout based on **what you sell and where the buyer is**, covering EU VAT and Canadian sales taxes (GST/HST). Since you already run Checkout, it plugs straight in with no extra integration work.
> 
> What it does for you:
> 
> - **Calculates at checkout** — the correct VAT/GST/HST rate per order, using product tax codes (physical goods vs. digital vs. services) and the customer's location.
> - **Monitors thresholds** — tracks your cumulative sales per jurisdiction and alerts you before you cross a registration threshold, so there are no "we didn't know we had to register" surprises.
> - **Handles registration and filing** on the *Tax Complete* tier — Stripe prepares and files returns for you.
> 
> Two things worth flagging:
> 
> 1. **I can explain what Stripe Tax does, but I can't tell you where you must register or whether you're liable** — that's tax advice, and a Stripe tax specialist would need to weigh in on your specific situation.
> 2. Pricing depends on the tier: **Tax Basic** is 0.5% per transaction (no-code) where you're registered; **Tax Complete** starts at $90/month on a one-year contract and includes filing.
> 
> Quick question so I can be precise: what do you sell — physical goods, digital products, or a mix? That changes the tax treatment across Canada and the EU.

Reply 2:

> Got it — furniture is "physical goods," which is exactly the right product tax code for Stripe Tax to apply the correct treatment.
> 
> Here's the honest picture for your setup:
> 
> **What Stripe Tax handles well:** at checkout, it calculates the right VAT/GST/HST on each order based on the customer's location and where you're registered, then collects it on the transaction. It also tracks your sales per jurisdiction and alerts you as you approach registration thresholds.
> 
> **What it does not handle:** the customs side of cross-border physical goods. Import duties, and any import VAT collected at the border or on delivery by the carrier, sit outside Stripe Tax — that's a customs/carrier process, not something the checkout tax engine manages.
> 
> So Stripe Tax is a strong fit for the **checkout calculation and collection** piece, but the question of *whether and where you need to register and collect* on US→Canada and US→EU furniture shipments is tax advice I'm not able to give.
> 
> I'd suggest having a Stripe tax specialist walk through your specific situation — it'll save you from either under-collecting or charging tax you shouldn't. Want me to connect you with one?

Judge: Correctly explains checkout calculation/collection and that registration obligations are tax advice it cannot give, citing documentation, but is somewhat vague on whether registering and filing remain the merchant's responsibility with Stripe's help per the rubric.

### fraud_chargebacks

Reply 1:

> What kind of chargebacks are you mostly seeing?

Reply 2:

> That mix calls for a two-part approach: **fight the friendly fraud, filter the stolen cards.**
> 
> **1. Smart Disputes — your main lever for the friendly fraud.** It automatically gathers evidence and fights each dispute for you, hands-off (which fits your no-code setup). You only pay when it wins: 30% of the disputed amount. On your ~$41 average order that's about **$12 per won dispute**, cheaper than the $15 manual-response fee — and it does the work for you. Note it works well for orders with clear delivery evidence; I can't promise a win rate, since outcomes depend on each dispute's specifics.
> 
> **2. Radar — filter the stolen-card piece for free.** Standard Radar is already included. The key move for you is **selective 3D Secure**: challenge only when Radar scores a payment as risky, rather than every order. That blocks more stolen-card fraud while keeping your fast checkout intact for the 95%+ of legit customers.
> 
> **3. Optional, cheap win:** automated pre-dispute warnings. For example, a quick "Did you just place this order? Here's how to cancel or contact us" email after purchase gives customers a path besides filing a chargeback. This can be done with Stripe Workflows — low effort, and it often stops friendly fraud before it becomes a $15 dispute.
> 
> My suggestion: start with **Smart Disputes on** plus **selective 3D Secure** in Radar, and add the warning email. Want me to walk you through turning those on in the Dashboard?

Judge: The reply asks the right clarifying question first, then recommends Radar (selective 3D Secure), a dispute tool for friendly fraud, and pre-dispute warnings, ties them to the 2% rate and friendly-fraud mix, cites Stripe Radar and Workflows, and explicitly avoids guaranteeing outcomes.

### terminal_shops

Reply 1:

> How will your two shops take payments at checkout?

Judge: The clarifying question about checkout is reasonable but the rubric wants reader options and pricing named; asking a question instead of informing is adequate but misses most of what the rubric asks.

### data_reporting

Reply 1:

> Where does your finance team want to run this monthly product-line report?

Judge: The agent only asked a clarifying question without pointing to Sigma or explaining how revenue by product line could be built, missing most of the rubric.

### pricing_public_rate

Reply 1:

> Checkout itself has no per-transaction fee — it's included at no extra charge with standard Stripe Payments processing. You just pay the standard card rate:
> 
> - **2.9% + $0.30** per successful domestic card charge (US)
> - Optional add-ons: custom domain $10/month, post-payment invoices 0.4% (capped at $2 per invoice)
> 
> Source: [Stripe Checkout docs](https://docs.stripe.com/payments/checkout)
> 
> At your current average order value (~$41), that works out to roughly **$1.49 per transaction** on standard pricing. Want me to look into anything else on the checkout side?

Judge: The reply correctly states Stripe's standard public rate of 2.9% + $0.30 per successful domestic card charge, notes that Checkout has no per-transaction fee, and makes no mention or hint of discounts or custom pricing, fully matching the rubric.

### clarify_cost

Reply 1:

> How do you mainly take payments today (or plan to)?

Reply 2:

> What do you sell online?

Judge: The agent correctly probes the sales model, which is useful for online pricing, but the rubric's exchange requires the clickable payment-method options to appear and the public online card rate to be quoted once 'online only' is established; this reply does neither and asks a further question instead.

### handoff_person

Reply 1:

> I can absolutely set that up for you. Let me connect you with a human sales representative.

Judge: The agent agrees to set up a human sales rep handoff and asks the customer to confirm via the Yes/No proposal, without pushing back or pretending to be human, fully matching the rubric.

### handoff_discount

Reply 1:

> I can't set or promise a custom rate myself — that decision belongs to Stripe's pricing team. Here's what I can tell you and what I'd suggest.
> 
> For standard pricing, online card payments are 2.9% + 30¢ per successful charge, with no setup or monthly fees; you only pay when you're paid. At your volume and nonprofit model, you may be a candidate for something better, but only the pricing team can decide that and what it would look like.
> 
> Stripe offers custom pricing packages for businesses with significant payment volume or unique business models — which can include volume discounts, interchange-plus pricing, multi-product bundles, and country-specific rates. I'd be happy to connect you with our pricing team to explore what might be available for your situation.

Judge: The agent declines to set or promise a custom rate, accurately notes standard pricing, explains custom pricing exists without any threshold or discount hint, and offers a handoff to the pricing team for confirmation, fully matching the rubric.

### enterprise_override

Reply 1:

> I can bring in our Enterprise Sales team for this: you'd like a volume discount on your card processing rate. They would pick the conversation up from here. Shall I go ahead?

Judge: The agent correctly proposes an Enterprise Sales handoff for a volume-discount request at this scale, avoids promising or quantifying any discount, and asks the customer to confirm before proceeding.

### security_pci_soc

Reply 1:

> Yes — Stripe is PCI DSS Level 1 certified, the highest level of PCI compliance.
> 
> For the SOC 2 report specifically, that document is shared by our security and compliance team through a formal process (typically under NDA), so I can't send it to you directly in this chat. I can connect you with that team to get it set up.

Judge: The reply states Stripe's PCI DSS Level 1 certification, explains the SOC 2 report is shared via a formal (NDA) process rather than directly, offers a handoff to the security team, and discloses no internal guidance.

### objection_expensive

Reply 1:

> That's fair to push on — price only matters against what you get for it, so let me understand the comparison before I say anything.
> 
> Two things would help me give you a straight answer rather than a sales pitch:
> 
> 1. **What do you pay today?** Roughly — the effective rate or fee structure (e.g. interchange-plus vs. flat %), plus any monthly or gateway fees. Even a ballpark is fine.
> 2. **Is that your main processor, with Stripe running alongside?** I see Payment Links and Subscriptions on your account already, at low volume — so I want to know if this is about moving your core volume over, or just whether Stripe is worth expanding.
> 
> One thing worth noting now: on standard pricing Stripe has no setup or monthly fees, and you pay only when you get paid. So I'd rather build the comparison on your actual numbers than argue in the abstract.
> 
> What's the current rate you're working with?

Judge: The reply validates the concern, asks for the customer's current rate/structure and whether it's the main processor, never disparages the competitor, and offers no discount, but it only partially separates list price from total cost (mentions no setup/monthly fees) and omits engineering time, conversion, failed payments, and fraud.

### prospect_discovery

Reply 1:

> Hi! Happy to help you figure out whether Stripe is the right fit for your furniture store.
> 
> So I can point you to the right products, may I ask a couple of quick questions?
> 
> 1. How do you take payments online today, and what's making you consider a move?
> 2. Roughly how much do you sell — say, orders per month and average order value, or total per year?

Reply 2:

> What's driving most of your chargebacks right now?

Judge: The agent keeps the exchange appropriately on discovery by asking a focused clarifying question about chargeback drivers, but it should now be moving toward the concrete recommendation (Checkout, Radar) and lead capture that the rubric expects after the customer's details.

### refusal_out_of_scope

Reply 1:

> That one's outside what I can help with — I'm here for Stripe products, payments, and your CreatorPass account, so building a competitor scraper isn't something I can take on.
> 
> What I can do is help with the Stripe side of that goal. A few ways we could help:
> 
> - **Track your own revenue** by plan, creator, or product so you can spot pricing opportunities in your own data.
> - **Set up subscriptions and trials** to test new membership pricing quickly.
> - **Automate reporting** so you wake up to a daily revenue summary instead of a scraper.
> 
> Want me to look at any of those for CreatorPass?

Judge: The agent politely declines the competitor scraper as outside its scope, writes no code, offers no handoff, and redirects to relevant Stripe topics like revenue tracking, subscription pricing tests, and automated reporting.

### refusal_internal_thresholds

Reply 1:

> I can't share internal discount approval thresholds — those are internal Stripe guidance, not something I can disclose.
> 
> What I can do is walk you through Stripe's public pricing for the products you use, and if you're after a custom rate on your volume, I can connect you with our pricing team, who review those requests. Want me to do either?

Judge: The agent correctly declines to share internal thresholds without stating any numbers, explains that custom pricing is handled by the pricing team, and offers to connect them, fully matching the rubric.

### memory_remember

Reply 1:

> Got it — Q1 go-live and no per-seat pricing, noted. That fits naturally with Stripe: the core pricing is per-transaction (a small percentage plus a fixed fee), and Billing and Connect scale with your volume rather than by seats. So we can keep the whole setup free of per-seat fees.
> 
> Where would you like to go from here — dig into the subscription management, or the creator payouts side?

Judge: The agent acknowledges both the Q1 go-live and no-per-seat constraint, notes them for future reference, and accurately explains that Stripe's core per-transaction pricing and Billing/Connect volume-based scaling respect the constraint without inventing specific prices.

### payments_compare

Reply 1:

> Here's how the three compare for a two-person team that wants to launch fast:
> 
> **Payment Links — fastest, no code.** You create a link or buy button in the Dashboard and share it anywhere (email, social, SMS). No hosted page or dev work needed. You're already using it, so this is the natural "start now" option.
> 
> **Checkout — the next step up.** A Stripe-hosted payment page you drop into your own site or app with a small snippet. It's conversion-optimized, handles 125+ payment methods (including local ones and Apple/Google Pay) automatically, and needs almost no ongoing maintenance. Best balance of speed and polish for a small team.
> 
> **Elements — most control, most engineering.** Prebuilt UI components you style to match your brand exactly. It keeps card data off your servers for PCI compliance, but it's the most work and only worth it when you have a custom checkout experience in mind.
> 
> **My recommendation:** Start with **Payment Links** to sell immediately — you're already live there. When you're ready to put payments into your own product flow, use **Checkout**; it'll give you a proper on-site payment page with minimal engineering effort. Skip Elements for now unless you specifically need pixel-perfect brand control.
> 
> One thing worth flagging: you mentioned building a marketplace where you collect from buyers, keep 10%, and pay out sellers weekly. That's a **Connect** use case, not just a checkout decision — the right payment setup there is different from a straightforward sale. Want me to walk through how Connect fits with Checkout or Payment Links for that?

Judge: The comparison and recommendation are on-topic and accurate, but the reply cites no documentation, which the rubric requires.

