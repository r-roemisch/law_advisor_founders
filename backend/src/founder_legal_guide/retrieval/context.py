"""What building blocks may use when they are constructed."""

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from ..models import ModelFactory
from ..settings import Settings


@dataclass(frozen=True)
class ComponentContext:
    settings: Settings
    models: ModelFactory
    utility_model_id: str

    def utility_llm(self) -> BaseChatModel:
        return self.models.chat(self.utility_model_id, temperature=0.0)
