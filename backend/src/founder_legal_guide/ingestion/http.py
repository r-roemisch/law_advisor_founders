"""HTTP downloads with an on-disk cache, so repeated ingestion runs don't hit official servers."""

import hashlib
import logging
import time
from pathlib import Path

import httpx

from ..settings import REPO_ROOT

log = logging.getLogger(__name__)

CACHE_DIR = REPO_ROOT / "data" / "cache"
USER_AGENT = "FounderLegalGuide/0.1 (educational legal-information project)"


class FetchError(RuntimeError):
    pass


class Fetcher:
    def __init__(
        self,
        cache_dir: Path = CACHE_DIR,
        refresh: bool = False,
        timeout: float = 60.0,
        retries: int = 2,
        backoff: float = 1.0,
    ):
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.retries = retries
        self.backoff = backoff
        self._client = httpx.Client(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )

    def get(
        self,
        url: str,
        *,
        headers: dict | None = None,
        params: dict | None = None,
        cache: bool = True,
        allow_multiple_choices: bool = False,
    ) -> bytes:
        """GET a URL. `cache=False` for answers that must be current, e.g. "latest version".
        `allow_multiple_choices` accepts HTTP 300, whose body lists alternative documents."""
        key = repr((url, sorted((headers or {}).items()), sorted((params or {}).items())))
        digest = hashlib.sha256(key.encode()).hexdigest()
        path = self.cache_dir / digest[:2] / digest
        if cache and path.exists() and not self.refresh:
            return path.read_bytes()
        response = self._get_with_retries(url, headers, params)
        if response.status_code != 200 and not (
            allow_multiple_choices and response.status_code == 300
        ):
            raise FetchError(f"GET {url} returned HTTP {response.status_code}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        log.info("fetched %s (%d bytes)", url, len(response.content))
        return response.content

    def _get_with_retries(
        self, url: str, headers: dict | None, params: dict | None
    ) -> httpx.Response:
        """Network hiccups (DNS, dropped connections, 5xx) are retried; refusals (4xx) are not."""
        for attempt in range(self.retries + 1):
            try:
                response = self._client.get(url, headers=headers, params=params)
                if response.status_code < 500 or attempt == self.retries:
                    return response
            except httpx.TransportError as exc:
                if attempt == self.retries:
                    raise FetchError(f"GET {url} failed: {exc}") from exc
            log.info("retrying %s (attempt %d)", url, attempt + 2)
            time.sleep(self.backoff * 2**attempt)
        raise AssertionError("unreachable")

    def close(self) -> None:
        self._client.close()
