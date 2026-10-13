"""US federal law adapters.

- uscode: the Office of the Law Revision Counsel's release points (USLM XML, one zip per title).
  The version is the release point, e.g. "PL 119-120" (current through Public Law 119-120).
- ecfr: the eCFR versioner API. The version is the part's latest amendment date.
"""

import io
import json
import re
import zipfile

from ...retrieval.types import SourceDocument
from ..http import FetchError
from ..registry import SourceEntry
from ..us_parsers import parse_ecfr, parse_uslm
from .base import ADAPTERS, SourceAdapter

USCODE_DOWNLOAD_PAGE = "https://uscode.house.gov/download.html"
USCODE_ZIP = "https://uscode.house.gov/download/releasepoints/us/pl/{congress}/{law}/xml_usc{title:02d}@{congress}-{law}.zip"
USCODE_LINK = "https://www.govinfo.gov/link/uscode/{title}/{section}?link-type=html"
ECFR_TITLES = "https://www.ecfr.gov/api/versioner/v1/titles.json"
ECFR_VERSIONS = "https://www.ecfr.gov/api/versioner/v1/versions/title-{title}.json"
ECFR_FULL = "https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title}.xml"
ECFR_PAGE = "https://www.ecfr.gov/current/title-{title}/part-{part}"


@ADAPTERS.register("uscode")
class USCodeAdapter(SourceAdapter):
    def fetch(self, entry: SourceEntry) -> list[SourceDocument]:
        congress, law = self.current_release_point()
        title = int(entry.ref["title"])
        archive = self.fetcher.get(USCODE_ZIP.format(congress=congress, law=law, title=title))
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as zf:
                xml = zf.read(next(n for n in zf.namelist() if n.endswith(".xml")))
        except (zipfile.BadZipFile, StopIteration) as exc:
            raise FetchError(f"Title {title}: no XML in release point archive") from exc
        sections = parse_uslm(xml, title, entry.ref["sections"])
        first = entry.ref["sections"][0].split("-")[0]
        url = USCODE_LINK.format(title=title, section=first)
        return [SourceDocument(entry.info(url), "en", tuple(sections), f"PL {congress}-{law}")]

    def current_release_point(self) -> tuple[str, str]:
        page = self.fetcher.get(USCODE_DOWNLOAD_PAGE, cache=False).decode("utf-8", errors="replace")
        points = re.findall(r"releasepoints/us/pl/(\d+)/(\d+[a-z]?)/", page)
        if not points:
            raise FetchError("No US Code release point found on the OLRC download page")
        return max(points, key=lambda p: (int(p[0]), int(re.sub(r"\D", "", p[1]))))


@ADAPTERS.register("ecfr")
class ECFRAdapter(SourceAdapter):
    def fetch(self, entry: SourceEntry) -> list[SourceDocument]:
        title, part = int(entry.ref["title"]), int(entry.ref["part"])
        titles = json.loads(self.fetcher.get(ECFR_TITLES, cache=False))["titles"]
        as_of = next(t["up_to_date_as_of"] for t in titles if t["number"] == title)
        versions = json.loads(
            self.fetcher.get(
                ECFR_VERSIONS.format(title=title), params={"part": str(part)}, cache=False
            )
        )["content_versions"]
        amended = max((v["amendment_date"] for v in versions), default=as_of)
        xml = self.fetcher.get(
            ECFR_FULL.format(date=as_of, title=title),
            params={"part": str(part)},
            headers={"Accept-Encoding": "gzip"},
        )
        sections = parse_ecfr(xml, title, entry.ref.get("sections"))
        url = ECFR_PAGE.format(title=title, part=part)
        return [SourceDocument(entry.info(url), "en", tuple(sections), f"amended {amended}")]
