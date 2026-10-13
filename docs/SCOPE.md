# Scope

> **Not legal advice.** The Founder Legal Guide provides general legal information only. It does not replace consultation with a qualified lawyer.

This file defines what the guide covers. Edit it to widen or narrow the scope. The corpus and the coverage checks follow it.

## Jurisdictions

| Jurisdiction | Role |
|---|---|
| EU | Core. Most AI, data and internet law lives here. |
| Germany | National law for incorporating, hiring and running a company. |
| US | The largest market for selling online. Covered from a **market-entry** perspective: an EU/German founder selling to US customers. |

Adding a further Jurisdiction should be a data task (new sources), not a redesign.

### US coverage

- **Federal:** FTC Act (unfair or deceptive practices, AI claims), COPPA, CAN-SPAM, Section 230, DMCA, ADA (web accessibility), US copyright on AI.
- **California:** CCPA/CPRA and CPPA regulations, plus the state's AI laws.
- **Delaware:** corporate law, limited to the Delaware flip (C-Corp formation for fundraising) and SAFEs.
- **Colorado, Texas:** AI laws only.
- **Other states:** a summary table of comprehensive privacy laws only, written by the project from each state's official sources.
- **Not covered:** a US-native founder's full legal landscape, and US employment law entirely (including contractor classification).

## Languages

Each Source is held in its official language (German law in German, EU law in English and German, US law in English). Founders can ask in English or German and get answers in the language they asked in. Quotations stay in the original language and come with a translation.

## Legal Areas

Depth is either **deep** (primary law, official guidance and practical how-tos) or **standard** (the essentials plus pointers).

| # | Legal Area | Depth | Examples |
|---|---|---|---|
| 1 | Company Formation & Governance | standard | GmbH/UG, Delaware C-Corp, shareholder agreements, director duties |
| 2 | Contracts & Terms | standard | Terms of service, B2B SaaS contracts, data processing agreements (DPAs), liability caps |
| 3 | Data Protection | **deep** | GDPR, ePrivacy/TDDDG, CCPA/CPRA, international transfers, cookies |
| 4 | AI Regulation | **deep** | AI Act (incl. Digital Omnibus 2026/1744), US state AI laws, copyright of training data and outputs |
| 5 | Platform & Internet Law | **deep** | DSA, e-commerce, consumer law, imprint (Impressum), Section 230, DMCA |
| 6 | Intellectual Property | standard | Trademarks, software copyright, open-source licences, IP assignment |
| 7 | Employment & Contractors | standard | Employment contracts, freelancer misclassification, remote hires |
| 8 | Cybersecurity & Product Rules | standard | NIS2, Cyber Resilience Act, product liability |
| 9 | Fundraising & Equity | standard | ESOP/VSOP, term sheets, convertible loans, SAFEs |

## Tier 3 sources

Only openly reusable or public-sector practical sources: gründerplattform.de, the IHKs (chambers of commerce), the US SBA, the FTC business blog, YC's public SAFE documents, other EU data protection authorities' guides (e.g. the CNIL, filed under EU), and similar. There are about 20–40 curated pages.

Guidance from a regulator that interprets a specific law (e.g. the FTC's COPPA FAQ, BSI on NIS2) is Tier 2. A regulator's general how-to pages (e.g. the FTC business blog) are Tier 3. Robots and TDM opt-outs are respected, and only short excerpts are shown, each with a link. See ADR 0006.

## Escalation Triggers

In these situations the guide tells the Founder to consult a lawyer. Triggers marked ⏱ are shown at the top of the answer.

1. A **legal letter** has been received: cease-and-desist (*Abmahnung*), lawsuit, or demand letter
2. **Regulator contact**: data protection authority, FTC, Bundesnetzagentur
3. ⏱ **Data breach** (the 72-hour GDPR notification clock)
4. Possible **criminal exposure**
5. An AI system that may be **prohibited or high-risk** under the AI Act
6. **International data transfers** without a clear legal basis
7. ⏱ **About to sign** financing documents, a shareholder agreement, or an IP assignment
8. **Dismissing an employee** in Germany

For triggers 3 and 5, general Guidance may follow the notice. For the others, the guide only explains what to prepare for the lawyer.

## Out of scope

- **Tax.** It is too volatile and too local. When a question touches tax, the guide says so and refers the Founder to a tax advisor (Steuerberater or CPA).
- **Personalised legal advice.** See ADR 0002.
- **Litigation and disputes**, beyond recognising them as an Escalation Trigger.
