"""Versioned, explicit JSON. Loading never regenerates geometry."""

import json
from pathlib import Path
from .validation import validate_scene
from .schema import Scene, SceneError
from typing import Union


def decode(text: str) -> Scene:
    """Parse and validate versioned JSON without regenerating or normalizing geometry."""
    try:

        def reject_constant(value: str) -> None:
            raise SceneError(f"JSON 非有限值 {value}")

        scene = json.loads(text, parse_constant=reject_constant)
        validate_scene(scene)
        return scene
    except (ValueError, TypeError, KeyError, OverflowError) as e:
        raise SceneError(f"场景文件无效：{e}") from e


def encode(scene: Scene) -> str:
    """Serialize validated actual geometry as inspectable UTF-8 JSON text."""
    validate_scene(scene)
    return json.dumps(scene, ensure_ascii=False, indent=2, allow_nan=False)


def save(scene: Scene, path: Union[str, Path]) -> None:
    """Write a validated scene to a local JSON file; path is caller-selected."""
    Path(path).write_text(encode(scene), encoding="utf-8")


def load(path: Union[str, Path]) -> Scene:
    """Read a local scene; preserve independent positions, dimensions and IDs."""
    return decode(Path(path).read_text(encoding="utf-8"))
