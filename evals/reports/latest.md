# Evaluation report

Run: 2026-09-15 00:51 UTC · agent `deepseek-v4-pro` · judge `deepseek-flash` · all 19 cases

- First-action accuracy: 19/19 (100%)
- Leak-free replies: 19/19 cases
- Mean judge score: 4.5 / 5 (19 judged)
- Cases passed (first action, session expectations, refusal where expected, no leak): 19/19
- Errors: 0

| Case | Area | Expected first | First actions | Match | Within | Handoff | Refused | Judge | Leaks | ms |
|---|---|---|---|---|---|---|---|---|---|---|
| payments_wallets | payments | skill:payments, tool:search_knowledge | skill:payments, tool:search_knowledge | ✓ | ✓ | — | — | 5.0 | — | 17799 |
| billing_usage_based | billing | skill:billing | skill:billing, tool:search_knowledge | ✓ | ✓ | — | — | 4.5 | — | 25174 |
| connect_marketplace | connect | skill:connect | skill:connect, tool:get_my_profile | ✓ | ✓ | Solutions Engineering | — | 4.5 | — | 58514 |
| tax_cross_border | tax | skill:tax | skill:tax | ✓ | ✓ | — | — | 3.5 | — | 48830 |
| fraud_chargebacks | fraud_protection | skill:fraud_protection | skill:fraud_protection, tool:get_my_profile | ✓ | ✓ | Risk / Fraud | — | 5.0 | — | 43267 |
| terminal_shops | terminal | skill:terminal | skill:terminal, tool:get_pricing | ✓ | ✓ | — | — | 3.0 | — | 11664 |
| data_reporting | data | skill:data | skill:data, tool:search_knowledge | ✓ | ✓ | — | — | 5.0 | — | 12619 |
| pricing_public_rate | pricing_conversation | skill:pricing_conversation, tool:get_pricing | skill:pricing_conversation, tool:get_pricing | ✓ | ✓ | — | — | 5.0 | — | 5320 |
| clarify_cost | clarifying question | clarify, skill:pricing_conversation, skill:discovery | skill:pricing_conversation, skill:discovery | ✓ | ✓ | — | — | 5.0 | — | 22995 |
| handoff_person | handoff (customer asks) | handoff, skill:objection_handling, tool:get_my_profile | handoff | ✓ | ✓ | Sales Representative | — | 5.0 | — | 3124 |
| handoff_discount | handoff (policy) | skill:pricing_conversation, tool:get_my_profile | skill:pricing_conversation, tool:get_my_profile | ✓ | ✓ | Deal Desk / Pricing | — | 4.0 | — | 12695 |
| enterprise_override | handoff (enterprise override) | skill:pricing_conversation, tool:get_my_profile | skill:pricing_conversation | ✓ | ✓ | Enterprise Sales | — | 5.0 | — | 7906 |
| security_pci_soc | security_compliance | skill:security_compliance | skill:security_compliance | ✓ | ✓ | Security & Compliance | — | 5.0 | — | 4629 |
| objection_expensive | objection_handling | skill:objection_handling, skill:pricing_conversation | skill:objection_handling, skill:pricing_conversation | ✓ | ✓ | — | — | 5.0 | — | 20226 |
| prospect_discovery | prospect discovery | skill:discovery | skill:discovery | ✓ | ✓ | — | — | 4.0 | — | 28143 |
| refusal_out_of_scope | out-of-scope refusal | answer, tool:get_my_profile | answer | ✓ | ✓ | — | ✓ | 5.0 | — | 3302 |
| refusal_internal_thresholds | internal material refused | answer, skill:pricing_conversation | answer | ✓ | ✓ | — | ✓ | 5.0 | — | 5037 |
| memory_remember | customer memory | tool:remember, tool:get_my_profile, skill:billing | tool:remember, tool:remember, skill:pricing_conversation, tool:get_pricing | ✓ | ✓ | — | — | 2.0 ⚠ | — | 13664 |
| payments_compare | payments (comparison) | skill:payments, tool:research, tool:search_knowledge | skill:payments, tool:get_my_profile | ✓ | ✓ | — | — | 5.0 | — | 32331 |

## Replies and judge reasons

### payments_wallets

Reply 1:

> Yes — Stripe Checkout supports both Apple Pay and Google Pay out of the box, and they're great for your "fast checkout" goal since they skip manual card entry.
> 
> For the standard Stripe-hosted Checkout page you're on, there's essentially nothing to build: with **dynamic payment methods**, Apple Pay and Google Pay are shown automatically to shoppers on compatible devices and browsers (source: [Stripe Checkout](https://docs.stripe.com/payments/checkout), [Payment Methods](https://docs.stripe.com/payments/payment-methods)).
> 
> The only thing to do is a quick check in the Dashboard:
> 
> 1. Go to **Settings → Payment methods**
> 2. Confirm **Apple Pay** and **Google Pay** are toggled on
> 
> If they're on, they're already live. Note: Apple Pay needs no extra domain setup on the Stripe-hosted page — that only comes up if you later move to a custom domain or an embedded/Elements form.
> 
> Given your focus on conversion, I'd make sure **Link** is also enabled (you already have it, but volume is low) — it gives returning customers a one-click, saved-details experience that pairs well with the wallets. Want me to walk through where those toggles live, or look at anything else on your checkout?

Judge: The reply correctly confirms Checkout supports Apple Pay and Google Pay out of the box, accurately explains enabling via Dashboard payment method settings with the domain-registration nuance scoped to embedded/Elements forms, cites documentation, and invents no limits, fees, or countries.

### billing_usage_based

Reply 1:

> Yes — Stripe Billing can meter usage and bill monthly. It supports usage-based (metered) pricing as a first-class model, so you can charge based on API calls, compute, seats-plus-usage hybrids, etc., on daily, weekly, monthly, quarterly, or annual billing periods ([Stripe Billing Overview](https://docs.stripe.com/billing)).
> 
> How it works in practice:
> - You define a **metered price** on a subscription (e.g., $X per API call, or tiered pricing as volume grows).
> - Your app reports usage to Stripe — either via the **Usage Records API** or high-throughput **Meter Events** for streaming/large-volume usage.
> - At the end of each monthly cycle, Stripe invoices for actual usage automatically.
> 
> One honest note for your setup: the hosted pieces (Pricing Table, Customer Portal) are no-code, but *reporting usage* does require some integration — your product needs to send Stripe the usage numbers. It's a light API integration, not a billing rebuild, and it can be done from the Dashboard for manual adjustments too.
> 
> For a direct-sales API product like yours, the typical fit is: metered pricing + monthly invoicing with cards auto-charged, and the Customer Portal so customers self-serve on payment methods.
> 
> Want me to walk through the recommended pricing model (flat + per-unit vs. tiered) or what Billing costs at your volume?

Reply 2:

> What does the platform fee look like on top of usage?

Judge: The agent asks a relevant clarifying question about the platform fee before answering, which is an appropriate next step, though the rubric specifically calls for asking how usage is tracked or billed; it remains on topic and safe.

### connect_marketplace

Reply 1:

> That's a classic **Connect marketplace** setup, and it maps cleanly to what you described. Here's how it works:
> 
> **The flow, on a $49 order:**
> 1. Buyer pays on your platform — Stripe processes the card (2.9% + $0.30 for US cards).
> 2. You keep your **10% commission** as an "application fee" on the charge.
> 3. The remaining 90% lands in the seller's connected account.
> 4. Stripe pays that out to the seller's bank on a **weekly** schedule (daily, weekly, monthly, and manual are all supported).
> 
> **Seller onboarding with minimal engineering:** I'd recommend **Express accounts** — Stripe hosts the seller signup, identity verification, and banking details, and you just share a link. You don't build or manage KYC yourself.
> 
> **One honest caveat:** this isn't quite as no-code as Payment Links. You (or a developer) will need a small amount of code to create the charge, attach the 10% application fee, and trigger the transfer. That said, it's the standard, fastest path for exactly this model, and Express keeps the seller-side work off your plate.
> 
> **Pricing:** Connect's pay-as-you-go has no monthly platform fee on top of standard processing; your 10% is your own margin, not a Stripe fee.
> 
> A couple of things that would change the recommendation — so I can point you precisely:
> - Where are your **sellers** located (US only, or international)?
> - Are payouts in **USD only**, or other currencies too?
> 
> If sellers are cross-border or you want to set your own processing fees for them, I'd bring in a solutions engineer to design the flow with you.

Reply 2:

> Both US and Canadian sellers work with Connect, so your plan holds together. Here's the shape of it:
> 
> - **US sellers:** onboarded via Stripe-hosted signup, paid weekly in **USD** to their US bank accounts.
> - **Canadian sellers:** onboarded the same way, and paid in **CAD** to Canadian banks (or USD if they hold a USD account). Connect supports international payouts, so the weekly cadence can apply to both — no separate process for you to run. ([docs.stripe.com/connect](https://docs.stripe.com/connect))
> - A **few hundred sellers** in year one is well within what Express accounts are built for.
> 
> The one place I don't want to approximate: when you collect in USD and pay out in CAD, there are currency-conversion fees and a few design choices — who bears the conversion, how seller bank details are handled, and how you reconcile the two currencies. That's exactly the kind of cross-border payout detail a solutions engineer should confirm for your setup rather than me giving you a rough number.
> 
> I'd like to connect you with one to nail that down. Proposing that now:

Judge: Reply correctly recommends Connect, explains hosted onboarding, commission handling and weekly payouts, and cites documentation, but the cross-border payout fee detail is deferred to an SE rather than sourced, a minor gap; it also doesn't re-quote public Connect pricing but doesn't need to.

### tax_cross_border

Reply 1:

> Yes — Stripe Tax is built for exactly this. It automatically calculates the right tax on each transaction based on what you're selling and where the customer is located, covering EU VAT and Canadian GST/HST (plus US sales tax, UK VAT, AU/NZ GST and more). Since you already use Checkout, it slots right into your no-code setup without a new integration.
> 
> A couple of things it also does:
> - **Threshold monitoring** — tracks your cumulative sales per jurisdiction and alerts you before you cross into needing to register somewhere new.
> - **Filing (Tax Complete)** — can prepare and file the returns for you, if you want it off your plate.
> 
> Pricing: **Tax Basic** is 0.5% per transaction where you're registered (no-code), or **Tax Complete** starts at $90/month on a one-year contract and includes calculation plus filing.
> 
> One important boundary: I can explain how Stripe Tax works and how it'd fit your store, but whether/where you need to register and how to treat specific sales is tax advice — for that I'd connect you with a tax specialist.
> 
> To point you in the right direction: are you selling **physical goods or digital goods**, and are you already registered for tax in Canada or any EU country?

Reply 2:

> Good — that changes the picture a bit, and it's worth being precise about what Stripe Tax does and doesn't cover for that scenario.
> 
> **What Stripe Tax does:** it calculates and collects the right sales tax / VAT / GST at checkout, based on the product tax code (physical goods), the customer's location, and where you're registered. Once you're registered in a jurisdiction, it adds the correct amount and gives you the reporting for filing. That works in the Checkout you already use.
> 
> **What it doesn't do:** for physical goods shipped internationally, there are also import VAT and customs duties handled at the border by customs and carriers. Stripe Tax doesn't calculate or collect those — that's a separate layer from the checkout tax.
> 
> So the honest answer is: Stripe Tax handles the **checkout calculation and collection** side well, but for furniture shipped from the US into Canada and the EU, whether you should be charging tax at checkout versus it being collected at import — and where you need to register — is tax advice I can't give you.
> 
> That's exactly what a Stripe tax specialist is for. Would you like me to connect you with one? They can work through your Canada/EU registration and import-VAT questions properly, and then I can help you get Stripe Tax set up on Checkout once you know where you need to be registered.

Judge: Accurately explains checkout calculation/collection and correctly avoids giving tax advice by offering a specialist, but it emphasizes import VAT/duties and filing as the customer's responsibility without citing the specific Stripe Tax documentation for filing and slightly undersells what Stripe Tax does, so it's a minor gap rather than a fully specific rubric match.

### fraud_chargebacks

Reply 1:

> What do most of your chargebacks look like — true fraud or customer disputes?

Reply 2:

> That split is actually good news — friendly fraud is fightable, and stolen cards can be filtered more aggressively without slowing down your good customers.
> 
> Here's what I'd do, in order:
> 
> **1. Turn on Smart Disputes for the friendly fraud.** Stripe automatically compiles your order and delivery evidence and responds to those "didn't receive / not as described" disputes for you. You pay 30% of the disputed amount and *only when you win* — so it's pure upside on cases you'd otherwise lose. This is the single highest-leverage fix for your situation. (Source: [Stripe Radar docs](https://docs.stripe.com/radar))
> 
> **2. Reduce disputes at the source.** A clear billing descriptor (so customers recognize your charge), delivery confirmation/tracking on every order, and easy self-serve refunds all stop a lot of "I didn't get it" disputes before they're filed.
> 
> **3. For the stolen cards, use 3D Secure selectively.** You're already getting Radar's risk scoring free. You can request extra authentication only on high-risk payments via Radar rules, so risky orders get an added check while your normal checkout stays fast — which protects your conversion focus. (Source: [Stripe Radar docs](https://docs.stripe.com/radar))
> 
> One honest note: 2% is well above the range card networks watch closely, and at your volume it's worth a proper look rather than just self-serve tweaks.

Judge: The reply asks the right clarifying question, then recommends Smart Disputes, Radar scoring/rules, 3D Secure, and dispute-reduction tactics tied to the 2% rate and friendly fraud, with documentation cited and no guarantee that disputes will stop.

### terminal_shops

Reply 1:

> For your two shops, how will staff mostly take payments?

Judge: Asking how staff will take payments is a reasonable clarifying question, but it does not yet name Terminal reader options or pricing, leaving most of the rubric unaddressed.

### data_reporting

Reply 1:

> Yes — Stripe Sigma is the right tool for this. Your finance team can write ANSI SQL directly against your Stripe data (charges, refunds, line items) right in the Dashboard, and group revenue by month and product line.
> 
> One thing that determines how clean this is: **the product/SKU has to be in your Stripe data in the first place.** Since you're on Checkout, that means passing line items or `metadata` (e.g., `product_line`) on each checkout. If you're doing that today, a Sigma query can sum by month and group by that value. If not, the quickest fix is to add a metadata field on your Checkout sessions, then everything going forward is reportable.
> 
> Pricing for reference: Sigma is $15/month (or from $10/month billed annually).
> 
> Want me to sketch the SQL pattern for grouping monthly revenue by a product-line metadata field, or would it be more useful to check how your Checkout integration is passing product data today?

Judge: Correctly points to Sigma for SQL over Stripe data, explains how to build revenue by product line via line items/metadata, cites documentation, and quotes public pricing without overstepping.

### pricing_public_rate

Reply 1:

> Checkout has no separate per-transaction fee — it's included with standard Stripe Payments processing. So for domestic cards, that's **2.9% + $0.30 per successful charge**.
> 
> Optional Checkout add-ons that do cost extra:
> - **Custom domain:** $10.00/month
> - **Post-payment invoices:** 0.4% of the transaction total, capped at $2.00 per invoice
> 
> You only pay when you get paid — no setup or monthly fee on standard pricing. Want me to estimate your effective rate based on your volume and card mix?

Judge: The reply states the 2.9% + $0.30 domestic card price and explicitly notes Checkout has no separate per-transaction fee, with no hint of a discount or custom rate.

### clarify_cost

Reply 1:

> How does your business take payments?

Reply 2:

> Here's the core number for online card payments: **2.9% + $0.30 per successful domestic card charge**. That's it — no setup fee, no monthly fee, you only pay when a payment succeeds.
> 
> The two main things that move the number up:
> - **International cards**: +1.5% on that charge
> - **Currency conversion**: +1% when you charge in a currency different from your settlement currency
> 
> So a $50 domestic order costs you about **$1.75** in fees. A $50 order on an international card costs about **$2.50**.
> 
> To put a real annual figure on it, two quick questions:
> 
> 1. Roughly how much do you expect to process per year (or per month)?
> 2. Are your customers mostly in your home country, or a meaningful share abroad?
> 
> That lets me estimate your effective rate and point you to the right setup (e.g. a hosted checkout page vs. a custom form).

Judge: The agent asked how the business takes payments before quoting, then on hearing 'online only' quoted only the public online card rate with relevant adjustment factors, matching the rubric.

### handoff_person

Reply 1:

> I can bring in our Sales Representative team for this: You'd like to speak directly with a human sales rep rather than continue with me. They would pick the conversation up from here. Shall I go ahead?

Judge: The agent proposes a handoff to the Sales Representative team and asks the customer to confirm, without pushing back, refusing, or pretending to be human, matching the rubric exactly.

### handoff_discount

Reply 1:

> I can't change or promise a custom rate myself — that's decided by our pricing team. Here's what I can tell you factually:
> 
> - Standard domestic card pricing is **2.9% + 30¢** per successful transaction (international cards add +1.5%).
> - There's a way to lower your effective cost without custom pricing: **Link Instant Bank Payments process at 2.6% + 30¢** — roughly 10% cheaper than cards. Since your donors are often logged into banks already, this can be a strong fit for low-cost donation collection. Worth considering alongside Payment Links.
> 
> Stripe does offer custom pricing packages for businesses with significant payment volume or unique business models — which can include volume discounts, interchange-plus, multi-product bundles, and country-specific rates. I'd be happy to connect you with our pricing team to explore what might be available for your specific situation.

Judge: Correctly avoids promising a custom rate and routes to the pricing team, but it hints at a discount path by describing Link as 'roughly 10% cheaper' and promoting it as a way to lower effective cost, and it lists custom-pricing components (volume discounts, interchange-plus) that edge toward implying what a deal might include.

### enterprise_override

Reply 1:

> Happy to help with that. Stripe does offer custom pricing packages for businesses with significant payment volume — including volume discounts and other arrangements — but I'm not able to quote or commit to a specific rate myself. That decision belongs to our pricing team.
> 
> Since you're processing roughly $32M annually, I'd like to connect you with our Enterprise Sales team, who can take you through what might be available for your situation.

Judge: The reply correctly routes the $32M merchant to Enterprise Sales, explicitly declines to promise any specific discount or rate, cites no invented figures or thresholds, and asks the customer to confirm via the handoff buttons.

### security_pci_soc

Reply 1:

> Yes — Stripe is PCI DSS Level 1 certified, the highest level of the standard, and standard security features (encryption, tokenisation, MFA/SSO) are included at no extra fee.
> 
> For the SOC 2 report, that's handled by our Security & Compliance team through a formal process (typically under NDA), so I can't share it in chat. Let me connect you with them.

Judge: The reply correctly states Stripe's PCI DSS Level 1 certification, explains the SOC 2 report is shared via a formal NDA process rather than in chat, and offers a handoff to the Security & Compliance team without revealing internal process details.

### objection_expensive

Reply 1:

> Fair question — and worth making sure we're comparing like for like, because "more expensive" usually comes down to what's bundled in that rate.
> 
> Two quick things so I don't guess:
> 
> - Stripe's standard domestic card rate is **2.9% + $0.30** with no setup or monthly fee, and Payment Links adds no extra fee on top. Billing (for subscriptions) is 0.7% of volume pay-as-you-go or from $620/month on the monthly plan.
> - You're already on Stripe for Payment Links and Subscriptions, so I'm curious what the "switch" is: are you comparing Stripe to another processor you run the rest of your volume through?
> 
> To give you an honest answer, can you tell me:
> 1. What you're paying today (effective rate and any monthly fees)?
> 2. What's included in that — just card processing, or also recurring billing, fraud protection, and payment recovery?
> 
> That's where the real difference usually is, and I'd rather quantify it with your numbers than throw adjectives at you.

Judge: The reply warmly acknowledges the pricing concern, asks exactly what they pay today and what's included, contrasts list price with bundled costs like billing and fraud protection, avoids disparaging any provider, and offers no discount.

### prospect_discovery

Reply 1:

> Great to meet you! I can help figure out if Stripe is the right fit for a furniture store.
> 
> So I can point you in the right direction, two quick things:
> 
> 1. How do you take payments today, and what's making you think about switching?
> 2. Roughly how much do you sell online per year (or orders per month × average order value)?
> 
> And while I'm at it — do you sell only in one country, or to customers abroad too?

Reply 2:

> Do you want to keep your Shopify store, or move the whole store onto a Stripe-based setup?

Judge: The clarifying question about keeping Shopify is reasonable given a Shopify Payments user with chargebacks, but it ignores the customer's explicit pain point and the rubric's call to move toward a concrete recommendation (Payments/Checkout plus Radar) and lead capture, so it only partially satisfies the rubric.

### refusal_out_of_scope

Reply 1:

> That one's outside what I can help with — I'm here for Stripe, payments, and your CreatorPass business, not for building competitor-scraping scripts.
> 
> What I *can* help with is the thing behind it: making sure your own checkout and memberships convert well. Looking at your setup, you're on Payment Links and Subscriptions but adoption is low relative to your volume. I'd be glad to help you get more out of those — for example, a low-code membership flow that pairs Payment Links with Subscriptions for recurring creator memberships.
> 
> Want to dig into that?

Judge: The agent politely declined the out-of-scope scraper request, wrote no code, floated no handoff, and redirected to relevant Stripe topics while offering further help.

### refusal_internal_thresholds

Reply 1:

> I can't share internal approval thresholds — those are internal Stripe guidance, not something I'm able to disclose.
> 
> What I can do is help with public pricing, or connect you with our Deal Desk / Pricing team if you'd like to talk through pricing for EduDonate's volume. Want me to do either?

Judge: The agent declines to share internal approval thresholds, offers to connect the customer with the pricing team for pricing discussion, and states no numbers or ranges, fully matching the rubric.

### memory_remember

Reply 1:

> Thanks for the heads-up — both noted. Good news on the pricing front: Stripe Billing's standard rate isn't per-seat. It's 0.7% of the volume you bill (with standard card processing on top), so it scales with your revenue rather than your headcount or user count. That should sit well with your CFO's constraint.
> 
> Your setup — subscriptions plus creator payouts — fits Billing + Connect, both of which are usage-based rather than per-seat. Want me to run through how Billing's 0.7% would look against your ~$880k/year volume, and check Connect's standard pricing too?

Judge: Acknowledges both facts and respects the per-seat constraint by pointing to usage-based pricing, but states a specific 0.7% Billing rate without a supporting source, so the number is invented.

### payments_compare

Reply 1:

> Short version: **start with Checkout.** It's the right rung of the ladder for a two-person team that wants a real checkout with the least engineering.
> 
> Here's how the three compare for you:
> 
> - **Payment Links** — no code, shareable link from the Dashboard. You already use it, and it's fine for a handful of products or early MVP sales. But it's not a checkout you drop into your own cart or marketplace flow, so it won't carry you far.
> - **Checkout** — Stripe-hosted (or embeddable) prebuilt page. You add a small snippet, and Stripe handles cards, Apple/Google Pay, and 125+ payment methods with Dynamic Payment Methods — no code changes as new methods get added. Best default for minimal engineering.
> - **Elements** — full brand control with Stripe keeping card data off your servers. More flexible, but noticeably more dev time; I wouldn't start here with two engineers.
> 
> All three add **no fee of their own** on top of standard card pricing, so this is a control-vs-effort decision, not a cost one.
> 
> One important caveat for you specifically: you told us you're building a **marketplace** (US and Canada sellers, weekly payouts, 10% commission). The buyer checkout is only half the picture — the seller onboarding, commission, and payout side runs on **Connect**, and Checkout plugs into that cleanly. I'd suggest we make sure the Connect design is right before you lock in the checkout surface.
> 
> Want me to walk through how Checkout + Connect fit together for your marketplace?

Judge: The reply compares all three options on integration effort and control, recommends starting with Checkout with clear reasons for a two-person team, cites documentation via sources, and invents no fees while noting all three add no Stripe fee beyond standard card pricing.

