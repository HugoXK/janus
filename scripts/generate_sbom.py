"""Generate a deterministic CycloneDX 1.5 SBOM for Janus.

This is a deliberate CycloneDX 1.5 *subset*, not a claim of full conformance:
only the fields the repository can honestly populate are emitted, and no
schema is vendored or validated over the network.

Two inventories are recorded, at different fidelity, because the repository
pins them differently:

* **Python — declared constraints.** There is no ``uv.lock``, so there is no
  resolved version to report. Each component comes from ``[project]
  dependencies`` or ``[project.optional-dependencies]``, carries the
  constraint itself in ``component.version`` (for example ``>=2.2``), the
  property ``janus:version_source = "declared-constraint"``, and a
  version-less ``pkg:pypi/<name>`` purl. A constraint such as ``>=2.2`` is not
  a purl version, so omitting it there is the decision, not an oversight.
* **npm — resolved versions.** Each component comes from
  ``dsh-plugin/package-lock.json``, carries the resolved version, the property
  ``janus:version_source = "lockfile"``, and a versioned
  ``pkg:npm/<name>@<version>`` purl.

The output is clock-free and content-addressed: no ``timestamp`` is emitted,
components are sorted, keys are sorted, and ``serialNumber`` is a ``uuid5``
over the canonical JSON of the document body. Two runs over identical inputs
are therefore byte-identical, and any input change changes the serial.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYPROJECT = REPO_ROOT / "pyproject.toml"
DEFAULT_LOCK = REPO_ROOT / "dsh-plugin" / "package-lock.json"

BOM_FORMAT = "CycloneDX"
SPEC_VERSION = "1.5"
BOM_VERSION = 1
SERIAL_NAMESPACE = uuid.NAMESPACE_URL

PROPERTY_VERSION_SOURCE = "janus:version_source"
PROPERTY_DEPENDENCY_GROUP = "janus:dependency_group"
PROPERTY_MARKER = "janus:marker"

SOURCE_DECLARED = "declared-constraint"
SOURCE_LOCKFILE = "lockfile"
RUNTIME_GROUP = "runtime"


class SbomError(Exception):
    """A fail-closed problem with an input or output path."""


def normalise_name(name: str) -> str:
    """PEP 503 name normalisation, without importing ``re``."""

    chars: list[str] = []
    for char in name.strip().lower():
        if char in "-_.":
            if chars and chars[-1] != "-":
                chars.append("-")
            continue
        chars.append(char)
    return "".join(chars).strip("-")


def split_requirement(requirement: str) -> tuple[str, str, str | None]:
    """Split ``name>=1; marker`` into a normalised name, constraint, marker."""

    body, _, marker = requirement.partition(";")
    body = body.strip()
    marker = marker.strip() or None

    end = 0
    while end < len(body) and (body[end].isalnum() or body[end] in "._-"):
        end += 1
    name = normalise_name(body[:end])
    constraint = body[end:].strip()
    if not name:
        raise SbomError(f"unparsable requirement: {requirement!r}")
    return name, constraint, marker


def _load_pyproject(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SbomError(f"pyproject not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SbomError(f"cannot read {path}: {exc}") from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SbomError(f"invalid TOML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SbomError(f"invalid TOML in {path}: expected a table")
    return data


def _load_lock(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SbomError(f"lockfile not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SbomError(f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SbomError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SbomError(f"invalid JSON in {path}: expected an object")
    return data


def _python_components(project: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    groups: list[tuple[str, list[Any]]] = []

    runtime = project.get("dependencies", [])
    if not isinstance(runtime, list):
        raise SbomError(f"invalid [project].dependencies in {path}")
    groups.append((RUNTIME_GROUP, runtime))

    optional = project.get("optional-dependencies", {})
    if not isinstance(optional, dict):
        raise SbomError(f"invalid [project.optional-dependencies] in {path}")
    for group in sorted(optional):
        requirements = optional[group]
        if not isinstance(requirements, list):
            raise SbomError(f"invalid [project.optional-dependencies].{group} in {path}")
        groups.append((str(group), requirements))

    components: list[dict[str, Any]] = []
    for group, requirements in groups:
        for requirement in requirements:
            name, constraint, marker = split_requirement(str(requirement))
            properties = [
                {"name": PROPERTY_VERSION_SOURCE, "value": SOURCE_DECLARED},
                {"name": PROPERTY_DEPENDENCY_GROUP, "value": group},
            ]
            if marker:
                properties.append({"name": PROPERTY_MARKER, "value": marker})
            components.append(
                {
                    "type": "library",
                    "name": name,
                    "version": constraint,
                    "purl": f"pkg:pypi/{name}",
                    "properties": properties,
                }
            )
    return components


def _npm_components(lock: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        raise SbomError(f"no 'packages' object in {path}")

    components: list[dict[str, Any]] = []
    for location in sorted(packages):
        if not location or location == ".":
            continue
        entry = packages[location]
        if not isinstance(entry, dict):
            raise SbomError(f"invalid package entry {location!r} in {path}")
        name = entry.get("name") or location.split("node_modules/")[-1]
        version = entry.get("version")
        if not name or not version:
            continue
        name = str(name)
        version = str(version)
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:npm/{name.replace('@', '%40')}@{version}",
                "properties": [
                    {"name": PROPERTY_VERSION_SOURCE, "value": SOURCE_LOCKFILE}
                ],
            }
        )
    return components


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def build_document(pyproject_path: Path, lock_path: Path) -> dict[str, Any]:
    pyproject = _load_pyproject(pyproject_path)
    lock = _load_lock(lock_path)

    project = pyproject.get("project")
    if not isinstance(project, dict):
        raise SbomError(f"missing [project] table in {pyproject_path}")
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not name:
        raise SbomError(f"missing [project].name in {pyproject_path}")
    if not isinstance(version, str) or not version:
        raise SbomError(f"missing [project].version in {pyproject_path}")

    components = _python_components(project, pyproject_path) + _npm_components(
        lock, lock_path
    )
    components.sort(key=lambda item: (str(item["name"]), str(item["purl"])))

    body: dict[str, Any] = {
        "bomFormat": BOM_FORMAT,
        "specVersion": SPEC_VERSION,
        "version": BOM_VERSION,
        "metadata": {
            "component": {"type": "application", "name": name, "version": version}
        },
        "components": components,
    }
    digest = hashlib.sha256(_canonical(body)).hexdigest()
    serial = uuid.uuid5(SERIAL_NAMESPACE, digest)
    return {"serialNumber": f"urn:uuid:{serial}", **body}


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_output(text: str, output: Path) -> None:
    temporary = output.with_name(output.name + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(output)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise SbomError(f"cannot write {output}: {exc}") from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic CycloneDX 1.5 SBOM for Janus."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="write the SBOM to this path instead of stdout",
    )
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=DEFAULT_PYPROJECT,
        help=f"pyproject to read (default: {DEFAULT_PYPROJECT})",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=DEFAULT_LOCK,
        help=f"npm lockfile to read (default: {DEFAULT_LOCK})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        document = build_document(args.pyproject, args.lock)
        text = render(document)
        if args.output is None:
            sys.stdout.write(text)
        else:
            write_output(text, args.output)
    except SbomError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
