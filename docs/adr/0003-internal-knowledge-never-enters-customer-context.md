# Internal knowledge never enters a customer conversation

The agent talks directly to customers, and the knowledge base contains documents
marked `internal_mock` - discount ranges, security-response tactics, qualification
playbooks - that must not be disclosed. Instead of indexing them and instructing the
model not to repeat them, we keep them out of the customer context structurally: the
retrieval tool only returns `public` chunks, and the guidance in the internal documents
is hand-translated into behavioural rules inside the relevant skills (what to say, when
to hand off), with their "client-ready" passages lifted as approved wording. A Stop hook
additionally scans replies for internal-document markers as a canary.

The trade-off is authoring effort: every change to an internal document means editing a
skill by hand. We accept that because a prompt-only "do not disclose" instruction can be
argued around, and a leak of pricing policy to a customer is not recoverable.
