"""Demo mode (DEMO_MODE=1): the whole app without an OpenRouter key.

No language model is involved. Answers list the retrieved passages, embeddings are word
hashes, and the Corpus is a handful of abridged sample excerpts held in memory. It exists so
the UI and the retrieval flow can be explored and shown without any cost.
"""

import hashlib
import json
import math
import re
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from .config import ComponentSpec, ModelChoice, ModelsConfig, StrategiesConfig, StrategySpec
from .disclaimer import DISCLAIMER
from .ingestion.adapters import ADAPTERS, SourceAdapter
from .ingestion.registry import SourceEntry
from .retrieval.types import Section, SourceDocument, SourceInfo

DEMO_NOTICE = "Demo mode: no language model is connected. Answers only list retrieved passages."

# Questions the small sample Corpus can answer: the demo only matches wording, not meaning.
DEMO_EXAMPLES = [
    "When must we report a personal data breach?",
    "Do we need a contract with a processor that handles personal data for us?",
    "Is an AI system that filters job applications high-risk?",
    "Must users be told that they are interacting with an AI system?",
    "Welche Angaben gehören ins Impressum unserer Website?",
    "Are we treated as the publisher of content our users post?",
]

_WORD = re.compile(r"\w+", re.UNICODE)
_PASSAGE = re.compile(
    r'<passage n="(\d+)" source="([^"]*)" tier="(\d)" jurisdiction="(\w+)" status="([^"]*)"'
    r' language="(\w+)">\n(.*?)\n(.*?)\n</passage>',
    re.DOTALL,
)
_GERMAN_HINTS = {
    "der",
    "die",
    "das",
    "und",
    "ist",
    "wir",
    "unser",
    "unsere",
    "welche",
    "müssen",
    "für",
}


def _spec(name: str, description: str, **overrides) -> StrategySpec:
    base = {
        "name": name,
        "description": description,
        "chunker": ComponentSpec(name="structure"),
        "embedding": "demo/hashing",
        "backend": "memory",
        "search": "hybrid",
        "query_transforms": [ComponentSpec(name="bilingual_expansion")],
        "top_k": 4,
    }
    return StrategySpec(**{**base, **overrides})


DEMO_STRATEGIES = StrategiesConfig(
    default="S1",
    strategies={
        "S1": _spec("S1", "Structure-aware chunks, hybrid search (demo)"),
        "S2": _spec(
            "S2",
            "Fixed-size chunks, hybrid search (demo)",
            chunker=ComponentSpec(name="fixed", params={"chunk_size": 300, "chunk_overlap": 50}),
        ),
        "S3": _spec("S3", "Structure-aware chunks, vector-only search (demo)", search="vector"),
    },
)

DEMO_MODELS = ModelsConfig(
    answer=[ModelChoice(id="demo/extractive", label="Demo (no language model)")],
    utility=ModelChoice(id="demo/utility"),
    judge=ModelChoice(id="demo/utility"),
)


class HashingEmbeddings(Embeddings):
    """Feature hashing of character 4-grams: similar wording gives similar vectors, and German
    compounds match their parts ("Impressumspflicht" ~ "Impressum"). No meaning, no cost."""

    def __init__(self, size: int = 2048, n: int = 4):
        self.size = size
        self.n = n

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.size
        for word in _WORD.findall(text.lower()):
            padded = f" {word} "
            for i in range(max(len(padded) - self.n + 1, 1)):
                gram = padded[i : i + self.n]
                bucket = int(hashlib.md5(gram.encode()).hexdigest(), 16) % self.size
                vector[bucket] += 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def _language(text: str) -> str:
    words = set(_WORD.findall(text.lower()))
    return "de" if words & _GERMAN_HINTS or re.search(r"[äöüß]", text.lower()) else "en"


class DemoUtilityModel(BaseChatModel):
    """Answers the utility prompts with safe no-op JSON, so transforms fall back gracefully."""

    @property
    def _llm_type(self) -> str:
        return "demo-utility"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        system = str(messages[0].content)
        if "translate" in system:
            reply: Any = {"language": _language(str(messages[-1].content)), "translation": ""}
        else:
            reply = []
        return ChatResult(generations=[ChatGeneration(message=AIMessage(json.dumps(reply)))])


class DemoAnswerModel(BaseChatModel):
    """Lists the top retrieved passages with citations. With tools bound it searches once first."""

    tool_names: tuple[str, ...] = ()

    @property
    def _llm_type(self) -> str:
        return "demo-extractive"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"tool_names": tuple(t.name for t in tools)})

    def _reply(self, messages) -> AIMessage:
        question = next(
            (str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)), ""
        )
        query = question.split("Passages:")[0].removeprefix("Question:").strip()
        called = {m.name for m in messages if isinstance(m, ToolMessage)}
        for name, args in _demo_tool_plan(query):
            if name in self.tool_names and name not in called:
                return AIMessage(
                    "", tool_calls=[{"name": name, "args": args, "id": f"demo-{name}"}]
                )
        passages = [
            match
            for m in messages
            if isinstance(m, HumanMessage | ToolMessage)
            for match in _PASSAGE.findall(str(m.content))
        ]
        checks = [
            _tool_line(m)
            for m in messages
            if isinstance(m, ToolMessage) and m.name != "search_corpus"
        ]
        return AIMessage(_compose(passages[:3], [c for c in checks if c]))

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        reply = self._reply(messages)
        if reply.tool_calls:
            call = reply.tool_calls[0]
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": call["name"],
                            "args": json.dumps(call["args"]),
                            "id": call["id"],
                            "index": 0,
                        }
                    ],
                )
            )
            return
        for word in re.findall(r"\S+\s*", str(reply.content)):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=word))
            if run_manager:
                run_manager.on_llm_new_token(word, chunk=chunk)
            yield chunk


def _demo_tool_plan(question: str) -> list[tuple[str, dict]]:
    """Which tools the demo calls, by keyword: a stand-in for a model's judgement."""
    q = question.lower()
    plan: list[tuple[str, dict]] = [("search_corpus", {"query": question})]
    if re.search(r"\b(ai|ki|high-risk|hochrisiko|llm|model)\b", q):
        args: dict = {}
        if re.search(r"job|recruit|cv|bewerb|application", q):
            args["annex_iii_area"] = "employment"
        if re.search(r"interact|chatbot|told|informed", q):
            args["interacts_with_people"] = True
        plan.append(("classify_ai_system", args))
    if re.search(r"\b(when|deadline|wann|frist|from when|ab wann)\b", q):
        plan.append(("compliance_timeline", {}))
    return plan


def _tool_line(message: ToolMessage) -> str:
    try:
        result = json.loads(str(message.content))
    except json.JSONDecodeError:
        return ""
    if message.name == "classify_ai_system" and "risk_class" in result:
        return f"AI Act rule check: {result['risk_class'].replace('_', ' ')}, role {result['role']}"
    if message.name == "compliance_timeline" and "events" in result:
        upcoming = [e for e in result["events"] if e["status"] == "upcoming"][:3]
        return "Upcoming dates: " + "; ".join(f"{e['date']} {e['source']}" for e in upcoming)
    return ""


def _compose(passages: list[tuple], checks: list[str] | None = None) -> str:
    if not passages:
        return (
            "**Short answer** – Demo mode found no matching passage in the small sample Corpus. "
            "Try one of the example questions.\n\n_" + DISCLAIMER + "_"
        )
    lines = [
        (
            "**Short answer** – Demo mode: no language model is connected, so this answer only "
            "lists the passages retrieved for your question. With a model, they would be turned "
            "into Guidance."
        ),
        "",
        "**What applies**",
    ]
    for n, _source, _tier, jurisdiction, status, _lang, label, text in passages:
        excerpt = text.strip().replace("\n", " ")
        excerpt = excerpt if len(excerpt) <= 220 else excerpt[:220].rsplit(" ", 1)[0] + " …"
        lines.append(
            f"- **{label}** ({jurisdiction}, {status.replace('_', ' ')}) [{n}]: “{excerpt}”"
        )
    if checks:
        lines += ["", "**Rule checks**", *(f"- {c} (rule check)" for c in checks)]
    lines += ["", f"_{DISCLAIMER}_"]
    return "\n".join(lines)


class DemoModelFactory:
    def chat(self, model_id: str, *, temperature: float = 0.2) -> BaseChatModel:
        return DemoAnswerModel() if model_id == "demo/extractive" else DemoUtilityModel()

    def embeddings(self, model_id: str) -> Embeddings:
        return HashingEmbeddings()


def _source(id: str, title: str, jurisdiction: str, areas: tuple[str, ...], url: str) -> SourceInfo:
    return SourceInfo(
        id=id,
        title=f"{title} (demo excerpt, abridged)",
        jurisdiction=jurisdiction,
        tier=1,
        legal_areas=areas,
        legal_status="in_force",
        url=url,
    )


_GDPR = _source(
    "eu-gdpr", "GDPR", "EU", ("data_protection",), "https://eur-lex.europa.eu/eli/reg/2016/679/oj"
)
_AI_ACT = _source(
    "eu-ai-act",
    "AI Act",
    "EU",
    ("ai_regulation",),
    "https://eur-lex.europa.eu/eli/reg/2024/1689/oj",
)
_DDG = _source(
    "de-ddg",
    "Digitale-Dienste-Gesetz (DDG)",
    "DE",
    ("platform_law",),
    "https://www.gesetze-im-internet.de/ddg/__5.html",
)
_S230 = _source(
    "us-section-230",
    "47 U.S.C. § 230",
    "US",
    ("platform_law",),
    "https://www.law.cornell.edu/uscode/text/47/230",
)

# Verbatim excerpts from the official texts (EUR-Lex consolidated versions, gesetze-im-internet.de,
# 47 U.S.C.), cut only at the marked "…". tests/test_demo.py checks them against saved copies.
SAMPLE_DOCUMENTS: list[SourceDocument] = [
    SourceDocument(
        _GDPR,
        "en",
        (
            Section(
                ("GDPR", "Art. 28(1)"),
                "Where processing is to be carried out on behalf of a controller, the controller shall use only "
                "processors providing sufficient guarantees to implement appropriate technical and organisational "
                "measures in such a manner that processing will meet the requirements of this Regulation and ensure "
                "the protection of the rights of the data subject.",
                anchor="art-28-1",
            ),
            Section(
                ("GDPR", "Art. 28(3)"),
                "Processing by a processor shall be governed by a contract or other legal act under Union or Member "
                "State law, that is binding on the processor with regard to the controller and that sets out the "
                "subject-matter and duration of the processing, the nature and purpose of the processing, the type "
                "of personal data and categories of data subjects and the obligations and rights of the controller. "
                "…",
                anchor="art-28-3",
            ),
            Section(
                ("GDPR", "Art. 33(1)"),
                "In the case of a personal data breach, the controller shall without undue delay and, where "
                "feasible, not later than 72 hours after having become aware of it, notify the personal data breach "
                "to the supervisory authority competent in accordance with Article 55, unless the personal data "
                "breach is unlikely to result in a risk to the rights and freedoms of natural persons. Where the "
                "notification to the supervisory authority is not made within 72 hours, it shall be accompanied by "
                "reasons for the delay.",
                anchor="art-33-1",
            ),
        ),
        "demo",
    ),
    SourceDocument(
        _AI_ACT,
        "en",
        (
            Section(
                ("AI Act", "Art. 6(2)"),
                "In addition to the high-risk AI systems referred to in paragraph 1, AI systems referred to in "
                "Annex III shall be considered to be high-risk.",
                anchor="art-6-2",
            ),
            Section(
                ("AI Act", "Annex III, point 4(a)"),
                "Employment, workers’ management and access to self-employment:\n"
                "(a) AI systems intended to be used for the recruitment or selection of natural persons, in "
                "particular to place targeted job advertisements, to analyse and filter job applications, and to "
                "evaluate candidates; …",
                anchor="annex-3-4a",
            ),
            Section(
                ("AI Act", "Art. 50(1)"),
                "Providers shall ensure that AI systems intended to interact directly with natural persons are "
                "designed and developed in such a way that the natural persons concerned are informed that they "
                "are interacting with an AI system, unless this is obvious from the point of view of a natural "
                "person who is reasonably well-informed, observant and circumspect, taking into account the "
                "circumstances and the context of use. …",
                anchor="art-50-1",
            ),
        ),
        "demo",
    ),
    SourceDocument(
        _DDG,
        "de",
        (
            Section(
                ("DDG", "§ 5 Abs. 1 – Allgemeine Informationspflichten"),
                "(1) Diensteanbieter haben für geschäftsmäßige, in der Regel gegen Entgelt angebotene digitale "
                "Dienste folgende Informationen, die leicht erkennbar und unmittelbar erreichbar sein müssen, "
                "ständig verfügbar zu halten:\n"
                "1. den Namen und die Anschrift, unter der sie niedergelassen sind, …\n"
                "2. Angaben, die eine schnelle elektronische Kontaktaufnahme und eine unmittelbare Kommunikation "
                "mit ihnen ermöglichen, einschließlich der Adresse für die elektronische Post, …",
                anchor="p5-1",
            ),
        ),
        "demo",
    ),
    SourceDocument(
        _S230,
        "en",
        (
            Section(
                ("47 U.S.C. § 230", "(c)(1)"),
                "No provider or user of an interactive computer service shall be treated as the publisher or "
                "speaker of any information provided by another information content provider.",
                anchor="c-1",
            ),
        ),
        "demo",
    ),
]


def sample_entry(doc: SourceDocument) -> SourceEntry:
    """A registry entry for a sample document, served by the demo_sample adapter."""
    return SourceEntry(
        id=doc.source.id,
        title=doc.source.title,
        jurisdiction=doc.source.jurisdiction,
        legal_areas=list(doc.source.legal_areas),
        tier=doc.source.tier,
        languages=[doc.language],
        legal_status=doc.source.legal_status,
        adapter="demo_sample",
        ref={"url": doc.source.url},
        update="auto",
    )


@ADAPTERS.register("demo_sample")
class SampleAdapter(SourceAdapter):
    """Serves the built-in sample documents; no network."""

    def fetch(self, entry: SourceEntry) -> list[SourceDocument]:
        return [d for d in SAMPLE_DOCUMENTS if d.source.id == entry.id]
