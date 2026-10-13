import pytest

from founder_legal_guide.registry import Registry, UnknownComponentError


def test_register_and_get():
    registry: Registry[object] = Registry("widget")

    @registry.register("a")
    class A:
        pass

    assert registry.get("a") is A
    assert "a" in registry
    assert registry.names() == ["a"]


def test_unknown_name_lists_registered_names():
    registry: Registry[object] = Registry("widget")
    registry.register("a")(type("A", (), {}))
    with pytest.raises(UnknownComponentError, match="Unknown widget 'b'. Registered: a"):
        registry.get("b")


def test_duplicate_registration_fails():
    registry: Registry[object] = Registry("widget")
    registry.register("a")(type("A", (), {}))
    with pytest.raises(ValueError, match="already registered"):
        registry.register("a")(type("B", (), {}))
