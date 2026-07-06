from __future__ import annotations

import importlib
import pkgutil

import house_of_wolves


def test_every_package_module_imports() -> None:
    """Verify that every package module imports."""
    failures: list[str] = []

    for module in pkgutil.walk_packages(house_of_wolves.__path__, house_of_wolves.__name__ + "."):
        try:
            importlib.import_module(module.name)
        except Exception as exc:  # pragma: no cover - failure detail path
            failures.append(f"{module.name}: {exc}")

    assert failures == []
