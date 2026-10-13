"""Parses EUR-Lex XHTML (Official Journal and consolidated versions, any language) into Sections.

Both formats mark structure with the same element ids, so parsing goes by id, not by CSS class:
  art_33 (article), art_33.tit_1 (its title), rct_12 (recital), anx_III (annex).
Amendment markers (►M1 / ▼M1) and footnote references are dropped.
"""

import re
import xml.etree.ElementTree as ET

from ..retrieval.types import Language, Section

_NS = "{http://www.w3.org/1999/xhtml}"
_ARTICLE = re.compile(r"^art_\d+[a-z]*$")
_RECITAL = re.compile(r"^rct_\d+$")
_ANNEX = re.compile(r"^anx_[IVXLC]+[a-z]*$|^anx_\d+$")
_BLOCK = {"p", "div", "tr", "li", "table", "tbody", "h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_CLASSES = {"modref", "arrow", "oj-note-tag", "footnote"}
_TITLE_CLASSES = {"title-article-norm", "oj-ti-art"}
_ANNEX_TITLE_CLASSES = {"title-annex-1", "title-annex-2", "oj-ti-grseq-1", "oj-doc-ti"}
# A line holding only a list marker, e.g. "(1)", "(a)", "4.", "—": joined with the next line.
_MARKER = re.compile(r"^(\(?[0-9]{1,3}[a-z]?\)|\(?[a-z]{1,4}\)|[0-9]{1,3}[a-z]?\.|[—–-])$")
_RECITAL_WORD = {"en": "Recital", "de": "Erwägungsgrund"}


class ParseError(ValueError):
    pass


def parse_eurlex_xhtml(data: bytes, citation_name: str, language: Language) -> list[Section]:
    """Recitals, articles and annexes in document order."""
    root = _parse(data)
    sections: list[Section] = []
    for elem in root.iter():
        elem_id = elem.get("id") or ""
        if _RECITAL.match(elem_id):
            sections.append(_recital(elem, elem_id, citation_name, language))
        elif _ARTICLE.match(elem_id):
            sections.append(_article(elem, elem_id, citation_name))
        elif _ANNEX.match(elem_id):
            sections.extend(_annex(elem, elem_id, citation_name))
    return [s for s in sections if s.text]


# Heading classes in Commission documents (proposals, staff working documents).
_COM_HEADINGS = (
    "Titrearticle",
    "ChapterTitle",
    "SectionTitle",
    "ManualHeading1",
    "ManualHeading2",
    "Exposdesmotifstitre",
    "Heading1",
    "Heading2",
)
# Older consolidated versions carry these classes but no article ids.
_ARTICLE_HEADINGS = ("title-article-norm", "oj-ti-art", "title-annex-1")
_ARTICLE_SUBTITLES = ("stitle-article-norm", "oj-sti-art", "title-annex-2")
_ARTICLE_LINE = re.compile(r"^(Article|Artikel|ANNEX|ANHANG)\s+[0-9IVXLC]+[a-z]*$", re.IGNORECASE)


def parse_commission_xhtml(data: bytes, citation_name: str) -> list[Section]:
    """Documents without article ids (e.g. Commission proposals): one text Section per heading."""
    return _split_at_headings(_parse(data), citation_name, _COM_HEADINGS, (), kind="text")


def parse_by_title_classes(data: bytes, citation_name: str) -> list[Section]:
    """Older consolidated versions without element ids: split at article and annex titles."""
    return _split_at_headings(
        _parse(data), citation_name, _ARTICLE_HEADINGS, _ARTICLE_SUBTITLES, kind="provision"
    )


def parse_legacy_html(data: bytes, citation_name: str) -> list[Section]:
    """Pre-XHTML Official Journal HTML (not well-formed XML): text lines, split at lines that
    read "Article N"; the line after it is taken as the article title when it looks like one."""
    lines = _html_lines(data.decode("utf-8", errors="replace"))
    sections: list[Section] = []
    heading, buffer = "", []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _ARTICLE_LINE.match(line):
            _flush(sections, citation_name, heading, buffer, "provision")
            heading, buffer = _article_label(line), []
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt and len(nxt) < 120 and not nxt.endswith((".", ":", ";")):
                heading, i = f"{heading} – {nxt}", i + 1
        else:
            buffer.append(line)
        i += 1
    _flush(sections, citation_name, heading, buffer, "provision")
    return sections


def _split_at_headings(
    root, citation_name, heading_classes, subtitle_classes, kind
) -> list[Section]:
    body = root.find(f"{_NS}body")
    body = body if body is not None else root
    sections: list[Section] = []
    heading, buffer = "", []
    for elem in body.iter():
        if _tag(elem) != "p" or _classes(elem) & _SKIP_CLASSES:
            continue
        line = _text(elem)
        if not line:
            continue
        classes = _classes(elem)
        if any(c.startswith(heading_classes) for c in classes):
            _flush(sections, citation_name, heading, buffer, kind)
            heading, buffer = (
                (_article_label(line) if kind == "provision" else line.lstrip("•· ")),
                [],
            )
        elif (
            subtitle_classes and any(c.startswith(subtitle_classes) for c in classes) and not buffer
        ):
            heading = f"{heading} – {line}" if heading else line
        else:
            buffer.append(line)
    _flush(sections, citation_name, heading, buffer, kind)
    return sections


def _flush(sections, citation_name, heading, buffer, kind) -> None:
    """Close a Section. Untitled text before the first article of an act is cover-page
    boilerplate and is dropped; in Commission documents it is the introduction and kept."""
    text = "\n".join(buffer).strip()
    if text and (heading or kind == "text"):
        path = (citation_name, heading) if heading else (citation_name,)
        sections.append(Section(path, text, kind=kind if heading else "text"))


def _article_label(line: str) -> str:
    line = line.replace("Article ", "Art. ").replace("Artikel ", "Art. ")
    return _annex_word(line) if line.isupper() else line


def _html_lines(html: str) -> list[str]:
    from html.parser import HTMLParser

    blocks = {"p", "div", "tr", "li", "br", "h1", "h2", "h3", "h4", "table"}

    class _Lines(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self.skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "head"):
                self.skip += 1
            elif tag in blocks:
                self.parts.append("\n")

        def handle_endtag(self, tag):
            if tag in ("script", "style", "head"):
                self.skip = max(self.skip - 1, 0)
            elif tag in blocks:
                self.parts.append("\n")

        def handle_data(self, data):
            if not self.skip:
                self.parts.append(re.sub(r"\s+", " ", data))

    parser = _Lines()
    parser.feed(html)
    return [line.strip() for line in "".join(parser.parts).split("\n") if line.strip()]


def _parse(data: bytes) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ParseError(f"Not well-formed XHTML: {exc}") from exc


def _classes(elem: ET.Element) -> set[str]:
    return set((elem.get("class") or "").split())


def _tag(elem: ET.Element) -> str:
    return elem.tag.removeprefix(_NS)


def _text(elem: ET.Element, skip: set[int] | None = None) -> str:
    """Readable text: one line per block element, list markers kept on their item's line."""
    parts: list[str] = []
    skip = skip or set()

    def walk(e: ET.Element) -> None:
        skipped = (
            id(e) in skip
            or _classes(e) & _SKIP_CLASSES
            or (_tag(e) == "a" and (e.get("id") or "").startswith("ntc"))
        )
        if not skipped:
            parts.append(_spaces(e.text))
            for child in e:
                walk(child)
                parts.append(_spaces(child.tail))
            tag = _tag(e)
            if tag == "td":
                parts.append(" ")
            elif tag in _BLOCK and "grid-list-column-1" not in _classes(e) or tag == "br":
                parts.append("\n")

    walk(elem)
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parts).split("\n")]
    merged: list[str] = []
    for line in filter(None, lines):
        if merged and _MARKER.match(merged[-1]):
            merged[-1] = f"{merged[-1]} {line}"
        else:
            merged.append(line)
    return "\n".join(merged)


def _spaces(text: str | None) -> str:
    """Source indentation is not content: collapse it, so only block elements break lines."""
    return re.sub(r"\s+", " ", text) if text else ""


def _first_text(elem: ET.Element, classes: set[str]) -> ET.Element | None:
    return next((e for e in elem.iter() if _classes(e) & classes), None)


def _article(elem: ET.Element, elem_id: str, citation_name: str) -> Section:
    number = _first_text(elem, _TITLE_CLASSES)
    subtitle = next((e for e in elem.iter() if e.get("id") == f"{elem_id}.tit_1"), None)
    label = _text(number) if number is not None else elem_id.removeprefix("art_")
    label = label.replace("Article ", "Art. ").replace("Artikel ", "Art. ")
    if subtitle is not None and (title := _text(subtitle)):
        label = f"{label} – {title}"
    skip = {id(e) for e in (number, subtitle) if e is not None}
    return Section((citation_name, label), _text(elem, skip), kind="provision", anchor=elem_id)


def _recital(elem: ET.Element, elem_id: str, citation_name: str, language: Language) -> Section:
    number = elem_id.removeprefix("rct_")
    label = f"{_RECITAL_WORD[language]} {number}"
    return Section((citation_name, label), _text(elem), kind="recital", anchor=elem_id)


def _annex(elem: ET.Element, elem_id: str, citation_name: str) -> list[Section]:
    """One Section per top-level numbered point, so citations can name "Annex III › 4."."""
    titles = [e for e in elem if _classes(e) & _ANNEX_TITLE_CLASSES]
    heading = " – ".join(
        _annex_word(_text(t)) if i == 0 else _text(t) for i, t in enumerate(titles)
    )
    heading = heading or elem_id.replace("anx_", "Annex ")
    points = [e for e in elem if "grid-list" in _classes(e)]
    if not points:
        skip = {id(t) for t in titles}
        return [Section((citation_name, heading), _text(elem, skip), anchor=elem_id)]

    sections = []
    intro_skip = {id(t) for t in titles} | {id(p) for p in points}
    intro = _text(elem, intro_skip)
    for point in points:
        marker_elem = next((c for c in point if "grid-list-column-1" in _classes(c)), None)
        marker = _text(marker_elem) if marker_elem is not None else ""
        body = _text(point)
        if intro and not sections:
            body = f"{intro}\n{body}"
        sections.append(
            Section(
                (citation_name, heading, marker or "–"),
                body,
                anchor=f"{elem_id}.{marker.strip('.()')}",
            )
        )
    return sections


def _annex_word(title: str) -> str:
    """ "ANNEX III" → "Annex III", "ANHANG III" → "Anhang III"."""
    word, _, rest = title.partition(" ")
    return f"{word.capitalize()} {rest}".strip()
