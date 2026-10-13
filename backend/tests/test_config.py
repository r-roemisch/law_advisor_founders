import pytest

from founder_legal_guide.config import ConfigError, load_models, load_strategies
from founder_legal_guide.settings import REPO_ROOT

from .conftest import write_config


def test_repository_config_is_valid():
    strategies = load_strategies(REPO_ROOT / "config" / "strategies.yaml")
    models = load_models(REPO_ROOT / "config" / "models.yaml")
    assert strategies.default in strategies.enabled()
    assert models.is_answer_model(models.default_answer)


def test_defaults_merge_into_each_strategy(tmp_path):
    write_config(
        tmp_path,
        """
default: A
defaults: {chunker: structure, embedding: e, backend: memory, search: hybrid, top_k: 5}
strategies:
  A: {}
  B: {chunker: {name: fixed, chunk_size: 300}, search: vector}
""",
    )
    config = load_strategies(tmp_path / "strategies.yaml")
    a, b = config.strategies["A"], config.strategies["B"]
    assert (a.chunker.name, a.search, a.top_k) == ("structure", "hybrid", 5)
    assert (b.chunker.name, b.chunker.params, b.search) == ("fixed", {"chunk_size": 300}, "vector")


@pytest.mark.parametrize(
    ("strategies", "message"),
    [
        (
            "default: A\nstrategies:\n  A: {chunker: nope, embedding: e, backend: memory, search: vector}",
            "Unknown chunker 'nope'",
        ),
        (
            "default: A\nstrategies:\n  A: {chunker: structure, embedding: e, backend: chroma, search: hybrid}",
            "does not support 'hybrid'",
        ),
        (
            "default: A\nstrategies:\n  A: {enabled: false, chunker: structure, embedding: e, backend: memory, search: vector}",
            "default strategy 'A' is missing or disabled",
        ),
        (
            "default: A\nstrategies:\n  A: {chunker: structure, embedding: e, backend: memory, search: vector, reranker: {name: magic}}",
            "Unknown reranker 'magic'",
        ),
        (
            "default: A\nstrategies:\n  OFF: {chunker: structure, embedding: e, backend: memory, search: vector}",
            "quote the name",
        ),
    ],
)
def test_invalid_strategies_fail_at_load(tmp_path, strategies, message):
    write_config(tmp_path, strategies)
    with pytest.raises(ConfigError, match=message):
        load_strategies(tmp_path / "strategies.yaml")
