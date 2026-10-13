"""Asking the utility model for small JSON answers."""

import json
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMJsonError(ValueError):
    pass


def ask_json(llm: BaseChatModel, system: str, user: str):
    reply = llm.invoke([SystemMessage(system), HumanMessage(user)])
    text = _FENCE.sub("", str(reply.content)).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMJsonError(f"Utility model returned invalid JSON: {text[:200]!r}") from exc
