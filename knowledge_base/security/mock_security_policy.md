# Mock Internal: Security & Compliance Response Policy

Product Line: Security
Product: Security
Topic: Internal Security Question Handling & Escalation
Source Type: mock_policy
Access Level: internal_mock
Sales Scenario: security_question_handling / compliance_escalation / enterprise_security_review
Last Updated: 2026-07-16
Source URL: internal://sales-playbook/security-response

## Summary

**INTERNAL ONLY — DO NOT SHARE WITH CUSTOMERS.** This document provides mock internal guidance for Stripe sales representatives handling customer security and compliance questions. It covers what information can be shared publicly, what requires escalation, standard security FAQ responses, and how to manage enterprise security review processes.

## Key Capabilities (Internal Guidelines)

### Information Sharing Policy (Mock)

**Can Share Publicly (No Escalation Needed):**
- Stripe is PCI DSS Level 1 certified
- SOC 1, SOC 2 Type II reports produced annually
- SOC 3 report is publicly available
- AES-256 encryption at rest, TLS 1.2+ in transit
- MFA, SSO, and access control features
- General description of Card Data Vault architecture
- Bug bounty program existence (HackerOne)

**Requires NDA & Formal Request (Escalate to Compliance Team):**
- Full SOC 2 Type II report
- Full PCI Attestation of Compliance (AOC)
- Penetration test summaries or results
- Detailed network architecture diagrams
- Business Continuity / Disaster Recovery plans
- Specific data center locations

**Can Never Share (Absolute Restriction):**
- Internal security incident post-mortems
- Raw security monitoring data or logs
- Specific encryption key management procedures
- Employee or system access credentials (obviously)
- Details of ongoing security investigations
- Customer data of other Stripe users

### Standard Security FAQ Responses (Mock Internal)

**Q: "Where is my data stored?"**
> A: Stripe stores data in secure data centers with multiple redundancies. For specific data residency requirements, please let us know which countries you need data stored in and we can verify against our current capabilities.

**Q: "Do you support on-premise deployment?"**
> A: Stripe is a cloud-native platform and does not offer on-premise deployment. Our cloud infrastructure is designed with defense-in-depth security including AES-256 encryption, tokenization via segregated infrastructure, and continuous monitoring.

**Q: "Are you HIPAA compliant?"**
> A: Stripe does not currently offer HIPAA-eligible services. If healthcare compliance is critical to your use case, I can escalate to our compliance team to discuss your specific requirements and potential alternatives.

**Q: "Can we conduct our own penetration test?"**
> A: Stripe maintains a bug bounty program via HackerOne and conducts regular independent penetration tests. Customer penetration tests against Stripe infrastructure are generally not permitted. I can connect you with our security team to discuss your specific testing needs.

**Q: "What happens during a security incident?"**
> A: Stripe maintains a 24/7 security on-call team and has established incident response procedures. In the event of a confirmed breach affecting customer data, Stripe will notify affected customers in accordance with regulatory requirements and our contractual obligations.

### Enterprise Security Review Process (Mock)
1. Customer initiates security review request via sales rep
2. Sales rep provides publicly available materials (SOC 3, security overview, PCI overview)
3. If customer requires SOC 2 or AOC, sales rep initiates NDA process with compliance team
4. Compliance team sends NDA for customer signature
5. Upon signed NDA, compliance team shares requested documents within 5 business days
6. For security questionnaires (SIG, VSAQ, custom), customer completes standard Stripe security questionnaire which compliance team reviews and returns
7. For security calls with customer's CISO/security team, escalate to Stripe security team for scheduling

## Sales Use Case

This document should be retrieved when an internal sales rep receives security or compliance questions from a customer, needs to understand what can and cannot be shared, or needs to navigate the enterprise security review process.

## Client-ready Explanation

**When asked security questions, use the approved public-facing responses in this document.** Never deviate from approved language on security topics. If the customer asks a question not covered here, respond with:

> "That's an excellent question. Let me connect you with our security team who can provide the most accurate and detailed answer for your specific requirements."

## Key Discovery Questions (Internal Use)

- What compliance certifications does the customer require?
- Is this a standard vendor assessment or a deep-dive security review?
- Does the customer have specific data residency or data sovereignty requirements?
- Is the customer in a regulated industry (healthcare, finance, government, education)?
- What is the customer's procurement timeline and what documents do they need?
- Has the customer's legal team already prepared an NDA for document sharing?

## Price

All standard security features are included. No additional fees for PCI compliance, encryption, MFA, or SSO.

## Escalation Notes

- **All SOC report requests beyond the public SOC 3 require NDA → escalate to compliance team**
- **Customer penetration test requests → escalate to security team (most will be declined)**
- **HIPAA, FedRAMP, or government-specific compliance questions → escalate to enterprise sales**
- **Security incident or vulnerability reports → direct to HackerOne bug bounty program**
- **Data residency questions for specific countries → escalate to product/engineering team**
- **Do not speculate, estimate, or make promises about security capabilities** — security misstatements create legal liability
- If a customer reports what appears to be a live security issue, follow the internal security incident reporting procedure immediately
