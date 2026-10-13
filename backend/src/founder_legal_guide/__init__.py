"""Founder Legal Guide backend. General legal information, not legal advice."""

import logging


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run("founder_legal_guide.api:create_app", factory=True, host="0.0.0.0", port=8000)
