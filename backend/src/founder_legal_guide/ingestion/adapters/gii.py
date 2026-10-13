"""gesetze-im-internet.de adapter: German federal law as XML (one zip per law, no login).

The text is the unofficial consolidated version. Its "Stand" notes say when it was last
amended and whether a recent amendment is still being incorporated; they travel with the
version string so the guide can show them.
"""

import io
import zipfile

from ...retrieval.types import SourceDocument
from ..gii_parser import parse_gii_xml
from ..http import FetchError
from ..registry import SourceEntry
from .base import ADAPTERS, SourceAdapter

ZIP_URL = "https://www.gesetze-im-internet.de/{slug}/xml.zip"
PAGE_URL = "https://www.gesetze-im-internet.de/{slug}/"


@ADAPTERS.register("gii")
class GiiAdapter(SourceAdapter):
    def fetch(self, entry: SourceEntry) -> list[SourceDocument]:
        slug = entry.ref["slug"]
        archive = self.fetcher.get(ZIP_URL.format(slug=slug))
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as zf:
                name = next(n for n in zf.namelist() if n.endswith(".xml"))
                xml = zf.read(name)
        except (zipfile.BadZipFile, StopIteration) as exc:
            raise FetchError(f"{slug}: no XML in archive") from exc
        law = parse_gii_xml(xml, entry.ref.get("sections"))
        # gii texts are German only; the citation name is the official abbreviation.
        sections = tuple(
            s
            if not entry.short_title
            else s.__class__(
                (entry.citation_name("de"), *s.heading_path[1:]), s.text, s.kind, s.anchor
            )
            for s in law.sections
        )
        version = "; ".join([law.build_date, *law.status_notes])
        return [SourceDocument(entry.info(PAGE_URL.format(slug=slug)), "de", sections, version)]
