import json
from .safety import check


def save_plan(scene: dict, plan: dict, path) -> None:
    """Save only a successful independently checked plan, with scene fingerprint."""
    check(scene, plan)
    from pathlib import Path

    Path(path).write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf8"
    )


def load_plan(scene: dict, path) -> dict:
    from pathlib import Path

    plan = json.loads(Path(path).read_text(encoding="utf8"))
    check(scene, plan)
    return plan
