"""EUR-Lex adapter: EU acts by CELEX number, via the Publications Office (no login needed).

- The latest consolidated version is found with the CELLAR SPARQL endpoint.
- Text comes as XHTML through content negotiation on publications.europa.eu, because
  eur-lex.europa.eu itself blocks scripted access.
- Consolidated versions contain no recitals, so recitals come from the original act.
"""

import json
import logging
import re

from ...retrieval.types import Language, Section, SourceDocument
from ..eurlex_parser import (
    parse_by_title_classes,
    parse_commission_xhtml,
    parse_eurlex_xhtml,
    parse_legacy_html,
)
from ..http import FetchError
from ..registry import SourceEntry
from .base import ADAPTERS, SourceAdapter

log = logging.getLogger(__name__)

SPARQL_URL = "https://publications.europa.eu/webapi/rdf/sparql"
RESOURCE_URL = "http://publications.europa.eu/resource/celex/{celex}"
EURLEX_URL = "https://eur-lex.europa.eu/legal-content/{lang}/TXT/?uri=CELEX:{celex}"
_LANG = {"en": "eng", "de": "deu"}

_CONSOLIDATED_QUERY = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?celex WHERE {{
  ?act cdm:resource_legal_id_celex ?base . FILTER(str(?base) = "{celex}")
  ?cons cdm:act_consolidated_consolidates_resource_legal ?act .
  ?cons cdm:resource_legal_id_celex ?celex .
  FILTER(STRSTARTS(str(?celex), "0{rest}"))
}}"""


@ADAPTERS.register("eurlex")
class EurLexAdapter(SourceAdapter):
    def fetch(self, entry: SourceEntry) -> list[SourceDocument]:
        celex = entry.ref["celex"]
        consolidated = self.latest_consolidated(celex)
        documents = []
        for language in entry.languages:
            try:
                sections, version = self._sections(entry, celex, consolidated, language)
            except FetchError as exc:
                log.warning("%s: no %s text: %s", entry.id, language, exc)
                continue
            url = EURLEX_URL.format(lang=language.upper(), celex=version)
            documents.append(SourceDocument(entry.info(url), language, tuple(sections), version))
        return documents

    def latest_consolidated(self, celex: str) -> str | None:
        """Newest consolidated CELEX (e.g. 02024R1689-20260727), or None if never consolidated.
        Only acts (sector 3) are consolidated; proposals and the like are not."""
        if not celex.startswith("3"):
            return None
        query = _CONSOLIDATED_QUERY.format(celex=celex, rest=celex[1:])
        data = self.fetcher.get(
            SPARQL_URL,
            params={"query": query},
            headers={"Accept": "application/sparql-results+json"},
            cache=False,
        )
        versions = [b["celex"]["value"] for b in json.loads(data)["results"]["bindings"]]
        return max(versions) if versions else None

    def _xhtml(self, celex: str, language: Language) -> bytes:
        return self.fetcher.get(
            RESOURCE_URL.format(celex=celex),
            headers={"Accept": "application/xhtml+xml", "Accept-Language": _LANG[language]},
        )

    def _sections(
        self, entry: SourceEntry, celex: str, consolidated: str | None, language: Language
    ) -> tuple[list[Section], str]:
        """The Sections plus the CELEX version they were actually taken from.

        Current text: the latest consolidated version, else the original act. Recitals: from
        the original act when it is available as XHTML (consolidations have none)."""
        name = entry.citation_name(language)
        if not celex.startswith("3"):
            return self._commission_document(celex, name, language), celex

        original = self._parsed(celex, name, language)
        current, version = None, celex
        if consolidated:
            try:
                current, version = self._parsed(consolidated, name, language), consolidated
            except FetchError:
                log.warning(
                    "%s: consolidated %s missing in %s; using the original act",
                    entry.id,
                    consolidated,
                    language,
                )
        if current is None:
            if original is None:
                raise FetchError(f"no text for {celex} in {language}")
            return original, celex
        recitals = [s for s in original or [] if s.kind == "recital"]
        provisions = [s for s in current if s.kind != "recital"]
        if not provisions and original:
            log.warning(
                "%s: no articles found in %s (%s); using the original act",
                entry.id,
                version,
                language,
            )
            provisions, version = [s for s in original if s.kind != "recital"], celex
        return recitals + provisions, version

    def _parsed(self, celex: str, name: str, language: Language) -> list[Section] | None:
        """Parse one CELEX document, trying XHTML by ids, then by title classes, then the
        legacy HTML of older Official Journal issues. None when the original act has no text;
        raises FetchError when a consolidated version is missing."""
        try:
            data = self._xhtml(celex, language)
        except FetchError:
            if celex.startswith("0"):
                raise
            try:
                legacy = self.fetcher.get(
                    RESOURCE_URL.format(celex=celex),
                    headers={"Accept": "text/html", "Accept-Language": _LANG[language]},
                )
            except FetchError:
                return None
            return parse_legacy_html(legacy, name)
        sections = parse_eurlex_xhtml(data, name, language)
        if not any(s.kind == "provision" for s in sections):
            sections = [s for s in sections if s.kind == "recital"] + parse_by_title_classes(
                data, name
            )
        return sections

    def _commission_document(self, celex: str, name: str, language: Language) -> list[Section]:
        """Proposals come as one or more documents (main text, annexes) listed in an HTTP 300
        answer, written in the Commission's own XHTML style."""
        listing = self.fetcher.get(
            RESOURCE_URL.format(celex=celex),
            headers={"Accept": "text/html", "Accept-Language": _LANG[language]},
            allow_multiple_choices=True,
        )
        links = re.findall(rb'href="([^"]+/DOC_\d+)"', listing)
        documents = [self.fetcher.get(link.decode()) for link in links] or [listing]
        return [section for doc in documents for section in parse_commission_xhtml(doc, name)]
