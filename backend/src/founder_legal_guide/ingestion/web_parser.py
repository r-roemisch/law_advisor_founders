"""Text extraction for web pages and PDFs (Tier 2 guidance and Tier 3 practical pages)."""

import io
import logging
import re
from html.parser import HTMLParser

from pypdf import PdfReader

# pypdf logs a warning for every unusual font encoding; extraction still works.
logging.getLogger("pypdf").setLevel(logging.ERROR)

from ..retrieval.types import Section

_SKIP_TAGS = {
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "noscript",
    "svg",
    "button",
}
_BLOCK_TAGS = {
    "p",
    "div",
    "li",
    "tr",
    "br",
    "section",
    "article",
    "table",
    "ul",
    "ol",
    "dd",
    "dt",
    "blockquote",
}
_HEADINGS = {"h1", "h2", "h3", "h4"}
_HEADING_MARK = "\x00H\x00"


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.main_depth = 0  # >0 while inside <main> or <article>
        self.saw_main = False
        self.main_parts: list[str] = []
        self.title = ""
        self._in_title = False
        self.tdm_reserved = False
        self.pdf_links: list[tuple[str, str]] = []
        self._link: str | None = None
        self._link_text: list[str] = []

    def _out(self) -> list[str]:
        return self.main_parts if self.main_depth else self.parts

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and (attrs.get("name") or "").lower() == "tdm-reservation":
            self.tdm_reserved = (attrs.get("content") or "").strip() == "1"
        if tag == "title":
            self._in_title = True
        if tag in _SKIP_TAGS:
            self.skip += 1
        if tag in ("main", "article"):
            self.main_depth += 1
            self.saw_main = True
        if tag == "a" and (attrs.get("href") or "").lower().split("?")[0].endswith(".pdf"):
            self._link, self._link_text = attrs["href"], []
        if not self.skip:
            if tag in _HEADINGS:
                self._out().append("\n" + _HEADING_MARK)
            elif tag in _BLOCK_TAGS:
                self._out().append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in _SKIP_TAGS:
            self.skip = max(self.skip - 1, 0)
        if tag in ("main", "article"):
            self.main_depth = max(self.main_depth - 1, 0)
        if tag == "a" and self._link:
            self.pdf_links.append((self._link, " ".join(self._link_text).strip()))
            self._link = None
        if not self.skip and (tag in _HEADINGS or tag in _BLOCK_TAGS):
            self._out().append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._link is not None:
            self._link_text.append(data.strip())
        if not self.skip:
            self._out().append(re.sub(r"\s+", " ", data))


class HtmlPage:
    def __init__(self, html: str):
        parser = _Extractor()
        parser.feed(html)
        self.title = re.sub(r"\s+", " ", parser.title).strip()
        self.tdm_reserved = parser.tdm_reserved
        self.pdf_links = parser.pdf_links
        raw = "".join(
            parser.main_parts
            if parser.saw_main and "".join(parser.main_parts).strip()
            else parser.parts
        )
        self.lines = [re.sub(r" +", " ", line).strip() for line in raw.split("\n")]

    def sections(self, citation_name: str) -> list[Section]:
        """Split at headings; text before the first heading gets the page title."""
        sections: list[Section] = []
        heading, buffer = "", []

        def flush():
            text = "\n".join(line for line in buffer if line)
            if len(text) >= 40:
                path = (citation_name, heading) if heading else (citation_name,)
                sections.append(Section(path, text, kind="text"))

        for line in self.lines:
            if line.startswith(_HEADING_MARK):
                title = line.removeprefix(_HEADING_MARK).strip()
                if title:
                    flush()
                    heading, buffer = title, []
            elif line:
                buffer.append(line)
        flush()
        return sections


def pdf_sections(data: bytes, citation_name: str) -> list[Section]:
    """One Section per page, so citations can point to "p. 12"."""
    reader = PdfReader(io.BytesIO(data))
    sections = []
    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
        text = "\n".join(line for line in lines if line)
        if len(text) >= 40:
            sections.append(
                Section((citation_name, f"p. {number}"), text, kind="text", anchor=f"page={number}")
            )
    return sections
