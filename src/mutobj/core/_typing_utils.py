from __future__ import annotations

import importlib
import sys
from typing import Any, ClassVar as ClassVarType, get_origin as _typing_get_origin


def _resolve_annotation_name(base: str, module_name: str) -> Any:
    """Resolve a string annotation base name in module globals."""
    parts = [part for part in base.split(".") if part]
    if not parts:
        return None

    root_name = parts[0]
    root: Any = None
    root_found = False

    module = sys.modules.get(module_name)
    if module is not None:
        module_globals = vars(module)
        if root_name in module_globals:
            root = module_globals[root_name]
            root_found = True

    if not root_found and root_name == "typing":
        root = importlib.import_module("typing")
        root_found = True

    if not root_found:
        return None

    obj = root
    for part in parts[1:]:
        try:
            obj = getattr(obj, part)
        except AttributeError:
            return None
    return obj


def is_classvar(annotation: Any, module_name: str) -> bool:
    if annotation is ClassVarType:
        return True
    origin = _typing_get_origin(annotation)
    if origin is not None and origin is ClassVarType:
        return True

    if isinstance(annotation, str):
        ann = annotation.strip()
        bracket = ann.find("[")
        base = ann[:bracket].strip() if bracket != -1 else ann

        if base == "ClassVar" or base == "typing.ClassVar":
            return True

        obj = _resolve_annotation_name(base, module_name)
        if obj is ClassVarType:
            return True
        origin2 = _typing_get_origin(obj)
        if origin2 is not None and origin2 is ClassVarType:
            return True

    return False
