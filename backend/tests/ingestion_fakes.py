"""Offline fakes for ingestion tests: a fetcher that serves saved official files."""

import gzip
import json
from pathlib import Path

from founder_legal_guide.ingestion.http import FetchError

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> bytes:
    return gzip.decompress((FIXTURES / name).read_bytes())


def sparql_answer(*celex: str) -> bytes:
    return json.dumps({"results": {"bindings": [{"celex": {"value": c}} for c in celex]}}).encode()


class FakeFetcher:
    """Serves responses by (url, Accept-Language); records every request."""

    def __init__(self, routes: dict[tuple[str, str | None], bytes]):
        self.routes = routes
        self.requests: list[tuple[str, dict]] = []

    def get(self, url, *, headers=None, params=None, cache=True, allow_multiple_choices=False):
        headers = headers or {}
        self.requests.append((url, {"headers": headers, "params": params, "cache": cache}))
        for key in ((url, headers.get("Accept-Language")), (url, None)):
            if key in self.routes:
                return self.routes[key]
        raise FetchError(f"GET {url} returned HTTP 404")

    def close(self) -> None:
        pass
