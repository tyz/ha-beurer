"""Unit tests for the CI path filter that scopes the mypy and pytest jobs."""

from __future__ import annotations

import pytest

from scripts.ci_scope import is_relevant


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "AGENTS.md",
        "README.bluetooth.md",
        "custom_components/beurer/translations/de.json",
        "custom_components/beurer/strings.json",
        "custom_components/beurer/manifest.json",
        "hacs.json",
        ".github/workflows/validate.yml",
    ],
)
def test_non_code_paths_skip_the_job(path: str) -> None:
    """Documentation, translations and workflow metadata cannot change a test result."""
    assert is_relevant("code", [path]) is False


@pytest.mark.parametrize(
    "path",
    [
        "custom_components/beurer/light.py",
        "custom_components/beurer/beurer.py",
        "tests/test_light.py",
        "tests/conftest.py",
        "requirements_test.txt",
        "mypy.ini",
        ".github/workflows/ci.yml",
        "scripts/ci_scope.py",
    ],
)
def test_code_paths_run_the_job(path: str) -> None:
    """Anything mypy reads or pytest imports has to run both jobs."""
    assert is_relevant("code", [path]) is True


def test_one_code_path_among_documentation_runs_the_job() -> None:
    """A single Python change is enough, regardless of what else the pull request touches."""
    assert is_relevant("code", ["README.md", "custom_components/beurer/config_flow.py", "TODO.md"]) is True


def test_markdown_inside_the_integration_does_not_run_the_job() -> None:
    """Only Python is checked in the source trees, not every file below them."""
    assert is_relevant("code", ["custom_components/beurer/README.md"]) is False


def test_no_changed_paths_skips_the_job() -> None:
    """An empty diff has nothing to check."""
    assert is_relevant("code", []) is False


def test_unknown_scope_is_rejected() -> None:
    """A typo in the workflow must fail loudly instead of silently skipping a job."""
    with pytest.raises(ValueError, match="unknown scope"):
        is_relevant("codez", ["custom_components/beurer/light.py"])
