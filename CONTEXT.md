# Founder Legal Guide

A legal guidance assistant for early-stage tech and AI founders, answering questions about the law they will encounter when building and selling software products in the EU, Germany and the US.

> **Not legal advice.** The Founder Legal Guide provides general legal information only. It does not replace consultation with a qualified lawyer.

## Language

### The user

**Founder**:
A non-lawyer building a tech company, from pre-incorporation to seed stage. The person asking questions.
_Avoid_: User (in domain talk), entrepreneur, client

**Founder Profile**:
The explicit context about a Founder that shapes retrieval and answers: stage, company seat, target markets, AI Role, customer type, and size bands.
_Avoid_: User settings, persona

**AI Role**:
The Founder's role under the AI Act, derived from plain-language questions: *none*, *deployer*, *provider*, or *GPAI model provider* (a provider of a general-purpose AI model). Fine-tuning a model and selling it can make a Founder a provider even if they think of themselves as "using AI".
_Avoid_: Build vs use, AI user, AI developer

### Scope

**Jurisdiction**:
A legal system whose law the guide covers: the EU, Germany, or the US.
_Avoid_: Country, region, market

**Legal Area**:
One of the fixed subject areas the guide covers, such as Data Protection or AI Regulation. The authoritative list lives in `docs/SCOPE.md`.
_Avoid_: Topic, category, practice area

### Sources

**Source**:
One legal document the guide draws on, such as an act, a code section, a guideline, or a commentary article. Each Source has exactly one Source Tier, one Jurisdiction, and one official language.
_Avoid_: Dataset, document (when the legal unit is meant), file

**Source Tier**:
The authority rank of a source. Tier 1 is primary law, Tier 2 is official guidance from regulators and authorities, and Tier 3 is curated secondary commentary.
_Avoid_: Source quality, trust level

**Source Registry**:
The editable list of every Source the guide should hold, together with where it comes from.
_Avoid_: Source list, config, dataset

**Corpus**:
The ingested, searchable content of every Source in the Source Registry at a given moment.
_Avoid_: Dataset, knowledge base (in domain talk), database

### Currency

**Legal Status**:
Where a Source stands in its legal life: *pending proposal*, *in force*, *applicable from <date>*, or *repealed*. Being in force and being applicable are distinct: an act can be in force while its obligations apply only later.
_Avoid_: Validity, state, version

**Pending Proposal**:
A Source that is not yet law, such as a Commission proposal or a bill. It is held in the Corpus but never presented as law in force.
_Avoid_: Draft law, upcoming law

**Change Record**:
An entry stating that a Source changed, what changed, and when it was detected. The Founder-facing "What changed" feed is made of these. A Change Record is either *applied* (the Corpus was updated automatically) or *review needed* (the change was detected, but a person must approve it before the Corpus changes).
_Avoid_: Update log, diff, changelog entry

### Completeness

**Coverage Map**:
For each Legal Area × Jurisdiction, the Sources that must be in the Corpus for that cell to count as covered.
_Avoid_: Checklist, scope matrix

**Gap Signal**:
Evidence that the Corpus lacks something a Founder needed: a question answered with weak retrieval, or answered from Tier 3 alone.
_Avoid_: Missing data, error

### Quality

**Retrieval Strategy**:
One named way of finding relevant passages in the Corpus, defined by how Sources are cut into passages, which embedding model represents them, where they are indexed, and how they are searched. It may also include rewriting the question before searching and re-ranking the results afterwards. Several strategies exist side by side so they can be compared, and new ones can be added at any time.
_Avoid_: RAG config, pipeline, setup

**Answering Mode**:
How the guide goes from a question to an answer: *single-pass* (search once, then answer) or *agentic* (the model decides what to search for and may search several times). It is independent of the Retrieval Strategy, which governs how each search works.
_Avoid_: Agent type, RAG type, flow

**Answer Model**:
The language model that writes the Founder-facing answer. It is distinct from the models that do supporting work (translation, personal-data checks) and from the model that scores evaluations.
_Avoid_: LLM, the model, chat model

**Golden Set**:
The reviewed list of test questions, each with the Sources it should retrieve and a reference answer. Retrieval Strategies are judged against it.
_Avoid_: Test data, benchmark, eval dataset

### Answers

**Guidance**:
Practical, non-personalised explanation of what the law requires and the steps typically taken to comply. It is never personalised legal advice.
_Avoid_: Legal advice, recommendation

**Rule Check**:
A deterministic check of the Founder's facts against written rules (AI Act classification, applicability thresholds, dated milestones, source currency). It is cited as a rule check, never as a Source.
_Avoid_: Tool, calculator, AI check

**Escalation Trigger**:
A situation in which the guide stops giving Guidance and tells the Founder to consult a lawyer. Examples are litigation, criminal exposure, high-risk AI classification, or international data transfers.
_Avoid_: Warning, disclaimer
