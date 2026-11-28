from __future__ import annotations

import json

import pytest

from scripts.release import bump_version, check_versions, main, read_versions


def _root(tmp_path):
    (tmp_path / "core/janus").mkdir(parents=True)
    (tmp_path / "dsh-plugin").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    (tmp_path / "core/janus/__init__.py").write_text('__version__ = "0.1.0"\n')
    (tmp_path / "dsh-plugin/package.json").write_text(
        json.dumps({"name": "@hugoxk/janus-dsh", "version": "0.1.0"}, indent=2) + "\n"
    )
    (tmp_path / "dsh-plugin/package-lock.json").write_text(
        json.dumps(
            {
                "name": "@hugoxk/janus-dsh",
                "version": "0.1.0",
                "lockfileVersion": 3,
                "packages": {"": {"name": "@hugoxk/janus-dsh", "version": "0.1.0"}},
            },
            indent=2,
        )
        + "\n"
    )
    return tmp_path


def test_versions_are_in_sync(tmp_path) -> None:
    root = _root(tmp_path)
    assert check_versions(root) == []
    assert {hit.value for hit in read_versions(root)} == {"0.1.0"}


def test_mismatch_is_reported(tmp_path) -> None:
    root = _root(tmp_path)
    package = root / "dsh-plugin/package.json"
    payload = json.loads(package.read_text())
    payload["version"] = "0.2.0"
    package.write_text(json.dumps(payload))
    errors = check_versions(root)
    assert len(errors) == 1
    assert "version mismatch" in errors[0]


def test_bump_writes_every_file_and_changelog(tmp_path) -> None:
    root = _root(tmp_path)
    changes = bump_version(root, "1.2.3", write=True, changelog_message="Big release")

    assert check_versions(root) == []
    assert all("-> 1.2.3" in value for value in changes.values())
    assert "1.2.3" in (root / "CHANGELOG.md").read_text()
    assert "Big release" in (root / "CHANGELOG.md").read_text()
    lock = json.loads((root / "dsh-plugin/package-lock.json").read_text())
    assert lock["version"] == "1.2.3"
    assert lock["packages"][""]["version"] == "1.2.3"


def test_dry_run_does_not_write(tmp_path) -> None:
    root = _root(tmp_path)
    bump_version(root, "2.0.0", write=False)
    assert {hit.value for hit in read_versions(root)} == {"0.1.0"}
    assert not (root / "CHANGELOG.md").exists()


def test_invalid_version_is_rejected(tmp_path) -> None:
    with pytest.raises(ValueError, match="semantic version"):
        bump_version(_root(tmp_path), "v2", write=True)


def test_expect_tag_match_and_mismatch(tmp_path, capsys):
    root = _root(tmp_path)
    assert main(["--root", str(root), "--expect-tag", "v0.1.0"]) == 0
    assert main(["--root", str(root), "--expect-tag", "v9.9.9"]) == 1
    assert "does not match" in capsys.readouterr().err
