"""Parses gesetze-im-internet.de XML (gii-norm.dtd) into Sections: one per § / Art. / Anlage.

Each <norm> carries its designation (<enbez>, e.g. "§ 26"), its title (<titel>) and its text.
The first norm holds the law's metadata, including the "Stand" notes that say when it was
last amended and whether an amendment is still being incorporated.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from ..retrieval.types import Section

_BLOCK = {"P", "DD", "row", "Title", "BR", "pre", "TOC"}
_SKIP = {"fussnoten", "FnR", "Footnotes", "SUP"}
_DESIGNATION = re.compile(
    r"^(?P<kind>§+|Art(?:ikel)?|Anlage)\s*(?P<num>\d+)\s*(?P<suffix>[a-z]*)", re.IGNORECASE
)
_RANGE = re.compile(
    r"^(?:(?P<kind>Art|Anlage|§)\s*)?(?P<start>\d+[a-z]*)(?:\s*-\s*(?P<end>\d+[a-z]*))?$"
)


class GiiParseError(ValueError):
    pass


@dataclass
class GiiLaw:
    abbreviation: str
    title: str
    build_date: str
    status_notes: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)


def parse_gii_xml(data: bytes, sections_filter: list[str] | None = None) -> GiiLaw:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise GiiParseError(f"Not well-formed gii XML: {exc}") from exc
    norms = root.findall("norm")
    if not norms:
        raise GiiParseError("No <norm> elements")
    meta = norms[0].find("metadaten")
    abbreviation = _first(meta, "amtabk") or _first(meta, "jurabk") or ""
    law = GiiLaw(
        abbreviation=abbreviation,
        title=_first(meta, "langue") or abbreviation,
        build_date=root.get("builddate", ""),
        status_notes=[
            f"{_first(s, 'standtyp')}: {_first(s, 'standkommentar')}"
            for s in meta.findall("standangabe")
        ],
    )
    ranges = [_parse_range(r) for r in sections_filter or []]
    for norm in norms[1:]:
        meta = norm.find("metadaten")
        designation = _first(meta, "enbez")
        unit = _first(
            meta.find("gliederungseinheit") if meta is not None else None, "gliederungsbez"
        )
        unit_title = _first(
            meta.find("gliederungseinheit") if meta is not None else None, "gliederungstitel"
        )
        title = _first(meta, "titel")
        if not designation and re.match(r"^Art(ikel)?\s", unit):
            # An article without numbered §§ (EGBGB Art 246): the unit itself carries the text.
            designation, title = unit, unit_title
        if not designation or designation in (
            "Inhaltsübersicht",
            "Eingangsformel",
            "Schlussformel",
        ):
            continue
        # In laws like the EGBGB an article is a structural unit ("Art 246a") whose norms are
        # numbered "§ 1", "§ 2": combine them into "Art 246a § 1".
        if designation.startswith("§") and re.match(r"^Art(ikel)?\s", unit):
            designation = f"{unit} {designation}"
        if ranges and not any(_in_range(designation, r) for r in ranges):
            continue
        content = norm.find("textdaten/text")
        text = _text(content) if content is not None else ""
        if not text or text.strip("()- ").lower() == "weggefallen":
            continue
        designation = re.sub(r"^Art(ikel)?\s", "Art. ", designation)
        label = f"{designation} – {title}" if title and title != "(weggefallen)" else designation
        law.sections.append(
            Section((abbreviation, label), text, kind="provision", anchor=_anchor(designation))
        )
    return law


def _first(elem: ET.Element | None, tag: str) -> str:
    if elem is None:
        return ""
    found = elem.find(tag)
    return re.sub(r"\s+", " ", "".join(found.itertext())).strip() if found is not None else ""


def _text(elem: ET.Element) -> str:
    """One line per paragraph; list markers (<DT>) stay on their item's line."""
    parts: list[str] = []

    def walk(e: ET.Element) -> None:
        if e.tag in _SKIP:
            return
        if e.tag == "DL":
            parts.append("\n")
        parts.append(re.sub(r"\s+", " ", e.text or ""))
        for child in e:
            walk(child)
            parts.append(re.sub(r"\s+", " ", child.tail or ""))
        if e.tag == "DT":
            parts.append(" ")
        elif e.tag in _BLOCK:
            parts.append("\n")
        elif e.tag == "entry":
            parts.append(" | ")

    walk(elem)
    lines = (line.strip(" |") for line in "".join(parts).split("\n"))
    return "\n".join(re.sub(r" +", " ", line) for line in lines if line.strip(" |"))


def _key(designation: str) -> tuple[str, int, str] | None:
    match = _DESIGNATION.match(designation.strip())
    if not match:
        return None
    kind = match["kind"].lower()
    kind = "§" if kind.startswith("§") else "art" if kind.startswith("art") else "anlage"
    return kind, int(match["num"]), match["suffix"].lower()


def _parse_range(spec: str) -> tuple[tuple, tuple]:
    match = _RANGE.match(spec.strip())
    if not match:
        raise GiiParseError(f"Invalid section range '{spec}'")
    kind = (match["kind"] or "§").lower()
    start = _key(f"{kind} {match['start']}")
    end = _key(f"{kind} {match['end'] or match['start']}")
    return start, end


def _in_range(designation: str, bounds: tuple[tuple, tuple]) -> bool:
    key = _key(designation)
    start, end = bounds
    return key is not None and key[0] == start[0] and start[1:] <= key[1:] <= end[1:]


def _anchor(designation: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "-", designation.replace("§", "p")).strip("-").lower()
