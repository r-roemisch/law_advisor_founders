"""Parsers for US federal law: US Code (USLM XML from the OLRC) and the eCFR (versioner XML)."""

import re
import xml.etree.ElementTree as ET

from ..retrieval.types import Section

_USLM = "{http://xml.house.gov/schemas/uslm/1.0}"
_USLM_SKIP = {"notes", "note", "sourceCredit", "toc", "meta"}
_USLM_BLOCK = {
    "subsection",
    "paragraph",
    "subparagraph",
    "clause",
    "subclause",
    "item",
    "subitem",
    "chapeau",
    "continuation",
    "content",
    "p",
}


# A line holding only a paragraph marker, e.g. "(1)", "(A)", "(ii)": joined with the next line.
_MARKER = re.compile(r"^\([0-9A-Za-z]{1,5}\)$")


class USParseError(ValueError):
    pass


def section_matches(number: str, ranges: list[str]) -> bool:
    """`number` like "230", "6502", "1798.100", "230.506"; ranges like "6501-6506" or "45"."""
    key = _number_key(number)
    for spec in ranges:
        start, _, end = spec.partition("-")
        if _number_key(start) <= key <= _number_key(end or start):
            return True
    return False


def _number_key(number: str) -> tuple:
    parts = re.findall(r"\d+|[a-z]+", number.lower())
    return tuple(int(p) if p.isdigit() else p for p in parts)


def parse_uslm(data: bytes, title: int, ranges: list[str]) -> list[Section]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise USParseError(f"Not well-formed USLM: {exc}") from exc
    sections = []
    prefix = f"/us/usc/t{title}/s"
    for elem in root.iter(f"{_USLM}section"):
        identifier = elem.get("identifier", "")
        if not identifier.startswith(prefix) or "/" in identifier[len(prefix) :]:
            continue
        number = identifier[len(prefix) :]
        if not section_matches(number, ranges):
            continue
        heading = _child_text(elem, "heading")
        text = _uslm_text(elem)
        if not text or "Repealed" in heading[:20]:
            continue
        label = f"§ {number} – {heading}" if heading else f"§ {number}"
        sections.append(
            Section((f"{title} U.S.C.", label), text, kind="provision", anchor=f"s{number}")
        )
    return sections


def _child_text(elem: ET.Element, tag: str) -> str:
    child = elem.find(f"{_USLM}{tag}")
    return re.sub(r"\s+", " ", "".join(child.itertext())).strip() if child is not None else ""


def _uslm_text(section: ET.Element) -> str:
    parts: list[str] = []

    def walk(e: ET.Element, top: bool) -> None:
        tag = e.tag.removeprefix(_USLM)
        if tag in _USLM_SKIP or (top and tag in ("num", "heading")):
            return
        if tag in _USLM_BLOCK:
            parts.append("\n")
        parts.append(re.sub(r"\s+", " ", e.text or ""))
        for child in e:
            walk(child, False)
            parts.append(re.sub(r"\s+", " ", child.tail or ""))

    for child in section:
        walk(child, True)
    lines = [re.sub(r" +", " ", line).strip() for line in "".join(parts).split("\n")]
    merged: list[str] = []
    for line in filter(None, lines):
        if merged and _MARKER.match(merged[-1]):
            merged[-1] = f"{merged[-1]} {line}"
        else:
            merged.append(line)
    return "\n".join(merged)


def parse_ecfr(data: bytes, title: int, ranges: list[str] | None) -> list[Section]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise USParseError(f"Not well-formed eCFR XML: {exc}") from exc
    sections = []
    for div in root.iter("DIV8"):
        number = div.get("N", "")
        if ranges and not section_matches(number, ranges):
            continue
        head = div.find("HEAD")
        label = (
            re.sub(r"\s+", " ", "".join(head.itertext())).strip()
            if head is not None
            else f"§ {number}"
        )
        lines = []
        for child in div:
            if child.tag in ("HEAD", "CITA", "EDNOTE", "SECAUTH"):
                continue
            line = re.sub(r"\s+", " ", "".join(child.itertext())).strip()
            if line:
                lines.append(line)
        if lines and not label.endswith("[Reserved]"):
            sections.append(
                Section(
                    (f"{title} CFR", label), "\n".join(lines), kind="provision", anchor=f"s{number}"
                )
            )
    return sections
