#!/usr/bin/env python3
"""Check and bump Janus release versions without third-party imports."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")
PYPROJECT_VERSION = re.compile(r'(?m)^version\s*=\s*"([^"]+)"')
INIT_VERSION = re.compile(r'(?m)^__version__\s*=\s*"([^"]+)"')


@dataclass(frozen=True)
class VersionHit:
    path: Path
    label: str
    value: str


def read_versions(root: Path) -> list[VersionHit]:
    hits = [
        VersionHit(
            root / "pyproject.toml",
            "pyproject.toml [project].version",
            _regex_version(root / "pyproject.toml", PYPROJECT_VERSION),
        ),
        VersionHit(
            root / "core/janus/__init__.py",
            "core/janus/__init__.py __version__",
            _regex_version(root / "core/janus/__init__.py", INIT_VERSION),
        ),
    ]
    package = json.loads((root / "dsh-plugin/package.json").read_text(encoding="utf-8"))
    hits.append(VersionHit(root / "dsh-plugin/package.json", "package.json", package["version"]))
    lock = json.loads((root / "dsh-plugin/package-lock.json").read_text(encoding="utf-8"))
    hits.append(
        VersionHit(
            root / "dsh-plugin/package-lock.json",
            "package-lock.json",
            lock.get("version") or lock["packages"][""]["version"],
        )
    )
    return hits


def _regex_version(path: Path, pattern: re.Pattern[str]) -> str:
    match = pattern.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"could not find version in {path}")
    return match.group(1)


def check_versions(root: Path) -> list[str]:
    hits = read_versions(root)
    values = {hit.value for hit in hits}
    if len(values) != 1:
        return [
            "version mismatch: " + ", ".join(f"{hit.label}={hit.value}" for hit in hits)
        ]
    version = hits[0].value
    if not SEMVER.match(version):
        return [f"invalid semantic version: {version}"]
    return []


def _replace_once(path: Path, pattern: re.Pattern[str], version: str) -> None:
    text = path.read_text(encoding="utf-8")
    replaced, count = pattern.subn(
        lambda match: match.group(0).replace(match.group(1), version),
        text,
        count=1,
    )
    if count != 1:
        raise ValueError(f"could not replace version in {path}")
    path.write_text(replaced, encoding="utf-8")


def bump_version(
    root: Path,
    version: str,
    *,
    write: bool = False,
    changelog_message: str = "",
) -> dict[str, str]:
    if not SEMVER.match(version):
        raise ValueError(f"invalid semantic version: {version}")
    changes = {hit.label: f"{hit.value} -> {version}" for hit in read_versions(root)}
    if write:
        _replace_once(root / "pyproject.toml", PYPROJECT_VERSION, version)
        _replace_once(root / "core/janus/__init__.py", INIT_VERSION, version)
        for name in ("package.json", "package-lock.json"):
            path = root / "dsh-plugin" / name
            payload = json.loads(path.read_text(encoding="utf-8"))
            if name == "package-lock.json":
                payload["version"] = version
                payload["packages"][""]["version"] = version
            else:
                payload["version"] = version
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        _update_changelog(root / "CHANGELOG.md", version, changelog_message)
    return changes


def _update_changelog(path: Path, version: str, message: str) -> None:
    heading = f"## [{version}]"
    text = path.read_text(encoding="utf-8") if path.exists() else "# Changelog\n"
    if heading in text:
        return
    entry = f"{heading}\n\n{message or 'Release ' + version}\n\n"
    lines = text.splitlines()
    insert_at = 1 if lines and lines[0].startswith("# ") else 0
    lines.insert(insert_at, "\n" + entry.rstrip())
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--bump", metavar="VERSION")
    parser.add_argument("--write", action="store_true", help="Actually modify files")
    parser.add_argument("--message", default="", help="Changelog entry for the bump")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.bump:
            changes = bump_version(
                root, args.bump, write=args.write, changelog_message=args.message
            )
            for label, change in changes.items():
                print(f"{label}: {change}")
            if not args.write:
                print("dry-run: pass --write to modify files")
            return 0
        errors = check_versions(root)
    except (OSError, ValueError, KeyError) as exc:
        print(f"release check failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"versions ok: {read_versions(root)[0].value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
