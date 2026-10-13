"""Name → class registries for pluggable building blocks (ADR 0007).

Each kind of building block (chunker, index backend, query transform, reranker,
Answering Mode) owns one Registry. Implementations register themselves by name,
and config files refer to them by that name.
"""

from collections.abc import Callable


class UnknownComponentError(LookupError):
    def __init__(self, kind: str, name: str, known: list[str]):
        super().__init__(f"Unknown {kind} '{name}'. Registered: {', '.join(known) or 'none'}")
        self.kind = kind
        self.name = name


class Registry[T]:
    def __init__(self, kind: str):
        self.kind = kind
        self._items: dict[str, type[T]] = {}

    def register(self, name: str) -> Callable[[type[T]], type[T]]:
        def decorator(cls: type[T]) -> type[T]:
            if name in self._items:
                raise ValueError(f"{self.kind} '{name}' is already registered")
            self._items[name] = cls
            return cls

        return decorator

    def get(self, name: str) -> type[T]:
        try:
            return self._items[name]
        except KeyError:
            raise UnknownComponentError(self.kind, name, self.names()) from None

    def names(self) -> list[str]:
        return sorted(self._items)

    def __contains__(self, name: str) -> bool:
        return name in self._items
