# Stripe Security & PCI Compliance

Product Line: Security
Product: Security
Topic: Security Posture & Compliance Certifications
Source Type: public_doc
Access Level: public
Sales Scenario: security_review / compliance_verification / enterprise_security
Last Updated: 2026-07-16
Source URL: https://docs.stripe.com/security

## Summary

Stripe maintains the highest level of security certification in the payments industry, including PCI DSS Level 1 (the most stringent level), SOC 1 and SOC 2 Type II reports (produced annually), and publicly available SOC 3 reports. Stripe's security program encompasses encryption at rest and in transit, tokenization via a segregated Card Data Vault, infrastructure hardening, continuous monitoring, and a corporate zero-trust security model.

## Key Capabilities

### Compliance Certifications
- **PCI DSS Level 1**: Highest level of PCI compliance — covers both Card Data Vault and secure software development
- **SOC 1 Type II**: Annual audit covering internal controls over financial reporting
- **SOC 2 Type II**: Annual audit covering security, availability, and confidentiality
- **SOC 3**: Publicly available summary report — shareable with customers
- **EMVCo Level 1 & 2**: Terminal certification for card reader security
- **PCI PA-DSS**: Terminal software security standard
- **NIST Cybersecurity Framework**: Security policies aligned with NIST standards
- **CBPR & PRP**: Asia-Pacific privacy certifications
- **EU-US DPF, UK Extension, Swiss-US DPF**: Data Privacy Framework compliance

### Data Protection
- **AES-256 encryption at rest**: All card numbers encrypted with AES-256; decryption keys stored on separate machines
- **TLS 1.2+**: HTTPS enforced for all services; HSTS preloaded in major browsers
- **Mutual TLS (mTLS)**: Internal server-to-server communication encrypted
- **Card Data Vault (CDV)**: PANs tokenized and isolated — raw card numbers never accessible to Stripe's internal servers
- **PGP keys**: Available for secure email communication

### Infrastructure Security
- **Frequent server rotation**: Automated server replacement to maintain health
- **Regular vulnerability scanning**: Third-party security firms conduct independent scans
- **Penetration testing & red team exercises**: Continuous security testing
- **Bug bounty program**: Via HackerOne — security researchers compensated for vulnerabilities
- **24/7 security on-call**: Dedicated security team across infrastructure, operations, privacy, and applications

### User Security Features
- **Multi-factor authentication**: Passkeys, hardware security keys, TOTP, SMS
- **Single Sign-On (SSO)**: SAML 2.0 with SCIM for centralized access management
- **Granular access control**: Team roles, restricted API keys with access policies, location-based restrictions
- **Security History**: Dashboard audit logs for monitoring account activity
- **GitHub Token Scanner**: Detects leaked API keys and alerts users
- **Login monitoring**: Alerts for unusual devices, IPs, or failed login attempts

## Sales Use Case

Use this document when a customer asks about Stripe's security certifications, needs compliance documentation for vendor assessment, wants to understand how Stripe protects payment data, or requires security assurances for an enterprise procurement process.

## Client-ready Explanation

Stripe's security is built to bank-grade standards. We are certified at PCI DSS Level 1 — the highest level in the payments industry — and undergo annual SOC 1 and SOC 2 Type II audits by independent auditors. All card data is encrypted using AES-256 and stored in a completely isolated infrastructure where raw card numbers are never accessible to our internal servers. We run continuous penetration testing, maintain a 24/7 security on-call team, and operate a public bug bounty program. For enterprises, we provide SOC reports, support SAML SSO with SCIM, and offer granular access controls with audit logging.

## Key Discovery Questions

- What compliance certifications does the customer require for their vendor assessment?
- Do they need copies of SOC reports, PCI Attestation of Compliance, or other audit documents?
- What is their data security review process and timeline?
- Do they require on-premise or private cloud deployment? (Note: Stripe is cloud-only)
- Do they need SSO/SAML integration for their team's Stripe Dashboard access?
- What level of access control do they need (roles, restricted API keys)?
- Are they in a regulated industry with additional compliance requirements (HIPAA, FedRAMP, etc.)?
- Do they have data residency requirements (data must stay in specific countries)?

## Price

All security features and certifications are included with Stripe's standard platform — no additional fees for PCI compliance, encryption, MFA, SSO, or security monitoring.

## Escalation Notes

- For SOC report requests, direct customers to the standard SOC report request process or escalate to compliance team
- If the customer requires HIPAA compliance, note that Stripe does not currently offer HIPAA-eligible services — escalate for verification of current status
- For FedRAMP or government-specific compliance requirements, escalate to enterprise sales
- If the customer requires data residency in specific countries beyond Stripe's current capabilities, escalate to product team
- For security incidents or vulnerability reports, direct to the official Stripe bug bounty program on HackerOne
- **Important**: Do not share SOC reports or security documentation without going through the proper request/NDA process
