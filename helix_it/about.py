from __future__ import annotations

import subprocess
from pathlib import Path

from helix_it import __version__


def app_version() -> str:
    return __version__


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )


def commits_behind_master(root: Path | None = None) -> tuple[int | None, str]:
    """Return (count, ref). count is None when this copy has no master ref."""
    root = root or _root()
    ref = ""
    for candidate in ("origin/master", "master"):
        if _git(root, "rev-parse", "--verify", "--quiet", candidate).returncode == 0:
            ref = candidate
            break
    if not ref:
        return None, ""
    result = _git(root, "rev-list", "--count", f"HEAD..{ref}")
    if result.returncode != 0:
        return None, ref
    try:
        return int(result.stdout.strip()), ref
    except ValueError:
        return None, ref
