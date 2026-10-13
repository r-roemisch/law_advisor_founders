"""Loads and validates config/strategies.yaml and config/models.yaml.

Validation happens at startup, so a typo in a component name fails loudly instead of
surfacing as a broken answer later.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from .registry import UnknownComponentError


class ConfigError(ValueError):
    pass


class ComponentSpec(BaseModel):
    """A building block reference: `{name: x, param: value, ...}` or just `x`."""

    name: str
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _split(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"name": data}
        if isinstance(data, dict) and "params" not in data:
            data = dict(data)
            name = data.pop("name", None)
            return {"name": name, "params": data}
        return data


class StrategySpec(BaseModel):
    name: str
    description: str = ""
    enabled: bool = True
    chunker: ComponentSpec
    embedding: str
    backend: str
    search: Literal["vector", "hybrid"]
    query_transforms: list[ComponentSpec] = Field(default_factory=list)
    reranker: ComponentSpec | None = None
    top_k: int = Field(default=8, ge=1, le=50)
    # Score multiplier per Source Tier: official law and guidance rank above practical pages (Q7).
    tier_weights: dict[int, float] = Field(default_factory=lambda: {1: 1.0, 2: 1.0, 3: 1.0})

    @property
    def index_name(self) -> str:
        """Strategies that cut and embed passages the same way share one index; search mode,
        query transforms, reranking and tier weights only change how it is searched."""
        name = f"{self.chunker.name}-{self.embedding.split('/')[-1]}"
        if self.chunker.params:
            digest = hashlib.sha1(
                json.dumps(self.chunker.params, sort_keys=True).encode()
            ).hexdigest()[:6]
            name += f"-{digest}"
        return name


class StrategiesConfig(BaseModel):
    default: str
    strategies: dict[str, StrategySpec]

    def enabled(self) -> dict[str, StrategySpec]:
        return {name: s for name, s in self.strategies.items() if s.enabled}


class ModelChoice(BaseModel):
    id: str
    label: str | None = None


class ModelsConfig(BaseModel):
    answer: list[ModelChoice] = Field(min_length=1)
    utility: ModelChoice
    judge: ModelChoice

    @property
    def default_answer(self) -> str:
        return self.answer[0].id

    def is_answer_model(self, model_id: str) -> bool:
        return any(m.id == model_id for m in self.answer)


def load_strategies(path: Path) -> StrategiesConfig:
    raw = _read_yaml(path)
    defaults = raw.get("defaults") or {}
    specs = {}
    for name, overrides in (raw.get("strategies") or {}).items():
        if not isinstance(name, str):
            raise ConfigError(
                f"{path.name}: strategy name {name!r} is not text; YAML reads words like "
                "ON/OFF/YES/NO as booleans, so quote the name"
            )
        try:
            specs[name] = StrategySpec(name=name, **{**defaults, **(overrides or {})})
        except ValidationError as exc:
            raise ConfigError(f"{path.name}: strategy '{name}' is invalid:\n{exc}") from exc
    config = StrategiesConfig(default=raw.get("default", ""), strategies=specs)
    _validate_strategies(config, path)
    return config


def _validate_strategies(config: StrategiesConfig, path: Path) -> None:
    from .retrieval import BACKENDS, CHUNKERS, QUERY_TRANSFORMS, RERANKERS

    if config.default not in config.enabled():
        raise ConfigError(
            f"{path.name}: default strategy '{config.default}' is missing or disabled"
        )
    for spec in config.strategies.values():
        try:
            CHUNKERS.get(spec.chunker.name)
            backend = BACKENDS.get(spec.backend)
            for transform in spec.query_transforms:
                QUERY_TRANSFORMS.get(transform.name)
            if spec.reranker:
                RERANKERS.get(spec.reranker.name)
        except UnknownComponentError as exc:
            raise ConfigError(f"{path.name}: strategy '{spec.name}': {exc}") from exc
        if spec.search not in backend.search_modes:
            raise ConfigError(
                f"{path.name}: strategy '{spec.name}': backend '{spec.backend}' does not support "
                f"'{spec.search}' search (supports: {', '.join(sorted(backend.search_modes))})"
            )


def load_models(path: Path) -> ModelsConfig:
    try:
        return ModelsConfig(**_read_yaml(path))
    except ValidationError as exc:
        raise ConfigError(f"{path.name} is invalid:\n{exc}") from exc


def _read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Missing config file: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must contain a mapping at the top level")
    return data
