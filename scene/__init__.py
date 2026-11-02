"""Public scene tools shared by CLI, UI and future geometry consumers."""

from .schema import DEFAULT, Config, Scene, SceneError
from .config import validate_config
from .generator import generate
from .validation import validate_scene, summary
from .storage import load, save, encode, decode
from .geometry import terrain_height
