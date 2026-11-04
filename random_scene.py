"""Random scene entry point with optional fixed-strip reachability checks.

Kept outside ``scene/`` so the pure scene layer never imports the planner.
"""

import hashlib
from typing import Any, Dict, Optional, Tuple

from scene.random_map import build
from scene.schema import Scene, SceneError


def _reachability(scene: Scene) -> Dict[str, Any]:
    from planning import generate_plan

    try:
        plan = generate_plan(scene, {})
    except (ValueError, TypeError) as error:
        return dict(
            checked=True,
            status="failed",
            reason=str(error),
            unreachable_targets=[],
        )
    if plan.get("status") == "success":
        return dict(
            checked=True,
            status="success",
            reason="",
            unreachable_targets=[],
        )
    return dict(
        checked=True,
        status="failed",
        reason=plan.get("reason") or "固定条带规划失败",
        unreachable_targets=[],
    )


def derive_seed(seed: int, attempt: int) -> int:
    """attempt 0 uses ``seed`` itself; retries use a hash-derived seed in
    [2**31, 2**32) so they never collide with another requested seed n+k."""
    if attempt == 0:
        return seed
    digest = hashlib.sha256(f"cwa-retry:{seed}:{attempt}".encode()).digest()
    return 2**31 + int.from_bytes(digest[:4], "big") % 2**31


def generate_with_report(
    style: str,
    seed: int,
    params: Optional[Dict[str, Any]] = None,
    require_reachable: bool = False,
    max_attempts: int = 50,
    check_reachability: bool = False,
) -> Tuple[Scene, Dict[str, Any]]:
    """Build a random scene and report its provenance and optional reachability.

    With ``require_reachable`` the seed is advanced per attempt; all failures
    are explicit and the last planning reason is returned instead of a
    pseudo-successful empty map.  Without it, generation never calls planning.
    """
    if type(require_reachable) is not bool:
        raise SceneError("require_reachable 必须是布尔值", field="require_reachable")
    # 随机装饰物可能贴住起降点；净空校验失败时换派生种子重试。
    attempts = max_attempts if (require_reachable or style == "random_obstacles_zones") else 1
    last_reason = ""
    for attempt in range(attempts):
        used_seed = derive_seed(seed, attempt)
        try:
            scene, report = build(style, used_seed, params)
        except SceneError as error:
            last_reason = str(error)
            if attempt + 1 >= attempts:
                raise
            continue
        report["attempts"] = attempt + 1
        report["seed_requested"] = seed
        report["seed_used"] = used_seed
        if require_reachable or check_reachability:
            reachability = _reachability(scene)
            report["reachability"] = reachability
            last_reason = reachability["reason"]
            if reachability["status"] == "success":
                return scene, report
            if not require_reachable:
                return scene, report
        else:
            return scene, report
    raise SceneError(
        f"已尝试 {attempts} 次仍无法满足固定条带规划：{last_reason}",
        field="require_reachable",
    )


def generate(
    style: str, seed: int, params: Optional[Dict[str, Any]] = None
) -> Scene:
    return generate_with_report(style, seed, params)[0]
