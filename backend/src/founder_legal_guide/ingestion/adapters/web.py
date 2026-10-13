"""Adapters for pinned web pages and PDFs: guidance and practical pages without a structured API.

Changes are detected by a hash of the extracted text, and they are marked "review needed"
(update: review in sources.yaml) because scraped text can break silently.

Reuse rules (ADR 0006): robots.txt and machine-readable TDM opt-outs (TDMRep's
/.well-known/tdmrep.json and the tdm-reservation meta tag) are honoured before text is used.
"""

import hashlib
import json
import logging
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from ...retrieval.types import SourceDocument
from ..http import USER_AGENT, FetchError
from ..registry import SourceEntry
from ..web_parser import HtmlPage, pdf_sections
from .base import ADAPTERS, SourceAdapter

log = logging.getLogger(__name__)


class ReuseNotAllowed(FetchError):
    """The site opts out of crawling or text and data mining for this page."""


@ADAPTERS.register("web_pinned")
class WebPageAdapter(SourceAdapter):
    follow_pdf = False  # landing pages that only summarise a PDF set this

    def fetch(self, entry: SourceEntry) -> list[SourceDocument]:
        url = entry.ref["url"]
        self._check_reuse_allowed(url)
        data = self.fetcher.get(url)
        language = entry.languages[0]
        name = entry.citation_name(language)
        if _is_pdf(url, data):
            sections = pdf_sections(data, name)
        else:
            page = HtmlPage(data.decode("utf-8", errors="replace"))
            if page.tdm_reserved:
                raise ReuseNotAllowed(
                    f"{url} reserves text and data mining (tdm-reservation meta tag)"
                )
            pdf_url = self._pdf_to_follow(url, page)
            if pdf_url:
                self._check_reuse_allowed(pdf_url)
                sections = pdf_sections(self.fetcher.get(pdf_url), name)
            else:
                sections = page.sections(name)
        if not sections:
            raise FetchError(f"{url}: no readable text")
        digest = hashlib.sha256("\n".join(s.text for s in sections).encode()).hexdigest()[:16]
        return [SourceDocument(entry.info(url), language, tuple(sections), f"sha256:{digest}")]

    def _pdf_to_follow(self, url: str, page: HtmlPage) -> str | None:
        if not self.follow_pdf or not page.pdf_links:
            return None
        host = urlparse(url).netloc.split(".", 1)[-1]
        candidates = [urljoin(url, href) for href, _ in page.pdf_links]
        same_site = [c for c in candidates if urlparse(c).netloc.endswith(host)]
        return (same_site or candidates)[0]

    def _check_reuse_allowed(self, url: str) -> None:
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        try:
            robots_txt = self.fetcher.get(f"{base}/robots.txt").decode("utf-8", errors="replace")
        except FetchError:
            robots_txt = ""  # no robots.txt: crawling is not restricted
        robots = RobotFileParser()
        robots.parse(robots_txt.splitlines())
        if robots_txt and not robots.can_fetch(USER_AGENT, url):
            raise ReuseNotAllowed(f"robots.txt of {parts.netloc} disallows {parts.path}")
        try:
            rules = json.loads(self.fetcher.get(f"{base}/.well-known/tdmrep.json"))
        except (FetchError, ValueError):
            return
        for rule in rules if isinstance(rules, list) else []:
            location = str(rule.get("location", ""))
            if rule.get("tdm-reservation") == 1 and _location_matches(location, parts.path):
                raise ReuseNotAllowed(
                    f"{parts.netloc} reserves text and data mining for {location} (TDMRep)"
                )


@ADAPTERS.register("edpb")
class EDPBAdapter(WebPageAdapter):
    """EDPB document pages summarise; the guideline itself is the linked PDF."""

    follow_pdf = True


@ADAPTERS.register("ec_digital")
class CommissionDigitalAdapter(WebPageAdapter):
    """Commission digital-strategy library pages; follow the PDF when one is linked."""

    follow_pdf = True


def _is_pdf(url: str, data: bytes) -> bool:
    return data[:5] == b"%PDF-" or urlparse(url).path.lower().endswith(".pdf")


def _location_matches(location: str, path: str) -> bool:
    pattern = location.rstrip("*")
    return (
        path.startswith(pattern)
        if location.endswith("*")
        else path == location or location in ("", "/")
    )
