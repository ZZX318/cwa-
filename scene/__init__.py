"""Public scene tools shared by CLI, UI and future geometry consumers."""

from .schema import DEFAULT, Config, Scene, SceneError
from .config import validate_config
from .generator import generate
from .validation import validate_scene, summary, report
from .storage import load, save, encode, decode
from .geometry import terrain_height
from .shapes import (
    rectangle_footprint,
    convex_footprint,
    prism,
    point_in_footprint,
    footprint_problems,
)
from .presets import PRESETS, preset_names, make_box
from .launch import resolve, resolve_all, role_of
from . import random_map
