"""Auto-discovery registry for worker skills.

Scans the ``skills/`` package for any module that contains a concrete
``BaseSkill`` subclass and registers it by its ``name`` property.

To add a new skill, just drop a ``.py`` file in ``skills/`` — no manual
registration needed.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

from skills.base import BaseSkill

_registry: dict[str, type[BaseSkill]] = {}
_discovered = False


def _discover():
    """Import every module in the skills package and collect BaseSkill subclasses."""
    global _discovered
    if _discovered:
        return
    _discovered = True

    package_dir = Path(__file__).resolve().parent
    for info in pkgutil.iter_modules([str(package_dir)]):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"skills.{info.name}")
        for _attr_name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseSkill) and obj is not BaseSkill:
                # Instantiate to read the name property, then register the class
                try:
                    instance = obj()
                    _registry[instance.name] = obj
                except Exception:
                    pass  # skip broken skills


def get_skill(name: str) -> BaseSkill:
    """Return a fresh instance of the skill identified by *name*.

    Raises ``KeyError`` if the skill is not found.
    """
    _discover()
    if name not in _registry:
        available = ", ".join(sorted(_registry)) or "(none)"
        raise KeyError(f"Unknown skill '{name}'. Available: {available}")
    return _registry[name]()


def list_skills() -> list[dict]:
    """Return metadata for all registered skills."""
    _discover()
    result = []
    for name, cls in sorted(_registry.items()):
        instance = cls()
        result.append({
            "name": instance.name,
            "description": instance.description,
        })
    return result
