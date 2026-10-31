"""Decide whether a CI job needs to run for the paths a pull request changes.

`mypy` and `pytest` install Home Assistant, which costs more than either check
itself, and a documentation-only pull request cannot affect either result. The
workflows ask this module before installing anything.

The module fails open: an unrecognised event, an unreadable diff or an unknown
scope prints ``true``. A skipped type check is worse than a slow one, so the
cheap mistake is to run a job that did not have to run.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterable, Sequence

# Files outside the two source trees that still change what mypy or pytest see.
_CODE_FILES = frozenset(
    {
        ".github/workflows/ci.yml",
        "mypy.ini",
        "pyproject.toml",
        "requirements_test.txt",
        "scripts/ci_scope.py",
    }
)

# Only the Python in these trees is checked or tested; their JSON files are
# covered by the manifest job instead.
_CODE_TREES = ("custom_components/beurer/", "tests/")


def _is_code(path: str) -> bool:
    """Return whether a single path can change the result of mypy or pytest."""
    if path in _CODE_FILES:
        return True
    return path.endswith(".py") and path.startswith(_CODE_TREES)


def is_relevant(scope: str, changed: Iterable[str]) -> bool:
    """Return whether any of the changed paths matters for ``scope``.

    Args:
        scope: The job scope to test for. Only ``"code"`` is defined.
        changed: Repository-relative paths changed by the pull request.

    Returns:
        True when the job has to run.

    Raises:
        ValueError: The scope is not one this repository knows about.
    """
    if scope != "code":
        raise ValueError(f"unknown scope {scope!r}")
    return any(_is_code(path) for path in changed)


def _changed_paths() -> list[str]:
    """Return the paths that differ between the base branch and this checkout.

    Requires a checkout with a usable ``origin/<base>`` ref, which the workflows
    get by asking for the full history.

    Returns:
        Repository-relative paths, empty when the pull request changes nothing.
    """
    base = f"origin/{os.environ['GITHUB_BASE_REF']}"
    completed = subprocess.run(
        ["git", "diff", "--name-only", base, "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.split()


def main(argv: Sequence[str]) -> int:
    """Print ``true`` when the job should run and ``false`` when it can be skipped.

    Args:
        argv: Command line arguments; ``argv[1]`` is the scope.

    Returns:
        Always 0, so that a failure here can never turn a job red.
    """
    scope = argv[1] if len(argv) > 1 else ""
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        # A push to main or a tag validates the whole repository, which is also
        # the safety net if a filter below is ever wrong.
        print("true")
        return 0
    try:
        changed = _changed_paths()
        relevant = is_relevant(scope, changed)
    except Exception as error:  # noqa: BLE001 - any failure must run the job
        print(f"ci_scope: {error!r}; running the job anyway", file=sys.stderr)
        print("true")
        return 0
    print(f"ci_scope: scope={scope} changed={len(changed)} relevant={relevant}", file=sys.stderr)
    print("true" if relevant else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
