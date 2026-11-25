"""SBOM generator contract (AC1-AC6 of #59).

Red on the unfixed tip: `ModuleNotFoundError: No module named 'scripts.generate_sbom'`
(the import below fails at collection; that IS the red).

Offline, deterministic, clock-free: every case runs the generator as a subprocess on
`tmp_path` inputs, except the source inspection which reads the module as text. Nothing
here touches the network or the real repository files, and no test asserts the literal
`[project].version` or schema version.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import scripts.generate_sbom  # noqa: F401 - pins the module; red is this import

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "generate_sbom.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"
LOCK = REPO_ROOT / "dsh-plugin" / "package-lock.json"

STDLIB_ALLOWLIST = {
    "__future__",
    "argparse",
    "hashlib",
    "json",
    "pathlib",
    "sys",
    "tomllib",
    "typing",
    "uuid",
}

GROUP_NAMES = ("runtime", "dev", "mcp", "data")


def _run(
    *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO_ROOT),
        check=False,
    )


def _toml() -> dict[str, Any]:
    import tomllib  # deferred: the 3.10 red run must fail on the missing module above

    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


def _project_version() -> str:
    return str(_toml()["project"]["version"])


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _split_requirement(requirement: str) -> tuple[str, str, str | None]:
    body, _, marker = requirement.partition(";")
    body = body.strip()
    marker = marker.strip() or None
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(.*)$", body)
    assert match is not None, f"unparsable requirement: {requirement!r}"
    return _normalise(match.group(1)), match.group(2).strip(), marker


def _expected_python() -> dict[str, tuple[str, str, str | None]]:
    project = _toml()["project"]
    expected: dict[str, tuple[str, str, str | None]] = {}
    for requirement in project["dependencies"]:
        name, constraint, marker = _split_requirement(requirement)
        expected[name] = (constraint, "runtime", marker)
    for group, requirements in project["optional-dependencies"].items():
        for requirement in requirements:
            name, constraint, marker = _split_requirement(requirement)
            expected[name] = (constraint, group, marker)
    return expected


def _expected_npm() -> dict[str, str]:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    packages: dict[str, str] = {}
    for path, entry in lock.get("packages", {}).items():
        if not path or path == ".":
            continue
        name = entry.get("name") or path.split("node_modules/")[-1]
        version = entry.get("version")
        if name and version:
            packages[name] = version
    return packages


def _props(component: dict[str, Any]) -> dict[str, str]:
    return {
        str(item["name"]): str(item["value"])
        for item in component.get("properties", [])
    }


def _components(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return list(doc["components"])


def _by_source(doc: dict[str, Any], source: str) -> dict[str, dict[str, Any]]:
    return {
        component["name"]: component
        for component in _components(doc)
        if _props(component).get("janus:version_source") == source
    }


def _serial_uuid(doc: dict[str, Any]) -> str:
    serial = str(doc["serialNumber"])
    assert serial.startswith("urn:uuid:"), serial
    return serial[len("urn:uuid:") :]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        keys = list(value)
        for item in value.values():
            keys.extend(_walk_keys(item))
        return keys
    if isinstance(value, list):
        keys: list[str] = []
        for item in value:
            keys.extend(_walk_keys(item))
        return keys
    return []


@pytest.fixture(scope="module")
def document(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    output = tmp_path_factory.mktemp("sbom") / "sbom.json"
    result = _run("--output", str(output))
    assert result.returncode == 0, result.stderr
    return json.loads(output.read_text(encoding="utf-8"))


# AC1 -----------------------------------------------------------------------


def test_writes_a_cyclonedx_1_5_document(document: dict[str, Any]) -> None:
    assert document["bomFormat"] == "CycloneDX"
    assert document["specVersion"] == "1.5"
    assert document["version"] == 1
    assert isinstance(document["version"], int)

    metadata = document["metadata"]["component"]
    assert metadata["type"] == "application"
    assert metadata["name"] == "janus-market"
    # A2: the version is read from pyproject at runtime, never hardcoded.
    assert metadata["version"] == _project_version()
    assert _components(document)


def test_without_output_prints_json_to_stdout_and_writes_nothing(tmp_path: Path) -> None:
    result = _run(cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["bomFormat"] == "CycloneDX"
    assert list(tmp_path.iterdir()) == []


# AC2 -----------------------------------------------------------------------


def test_python_components_follow_the_declared_constraints(
    document: dict[str, Any],
) -> None:
    expected = _expected_python()
    components = _by_source(document, "declared-constraint")

    assert len(expected) == 14
    assert set(components) == set(expected)
    for name, (constraint, group, marker) in expected.items():
        component = components[name]
        assert component["type"] == "library"
        assert component["version"] == constraint
        assert component["purl"] == f"pkg:pypi/{name}"
        props = _props(component)
        assert props["janus:version_source"] == "declared-constraint"
        assert props["janus:dependency_group"] == group
        if marker:
            assert props["janus:marker"] == marker
        else:
            assert "janus:marker" not in props


def test_dependency_groups_cover_the_four_declared_groups(
    document: dict[str, Any],
) -> None:
    groups = {
        _props(component)["janus:dependency_group"]
        for component in _by_source(document, "declared-constraint").values()
    }
    assert groups == set(GROUP_NAMES)


# AC3 -----------------------------------------------------------------------


def test_npm_components_carry_the_resolved_versions(document: dict[str, Any]) -> None:
    expected = _expected_npm()
    components = _by_source(document, "lockfile")

    assert expected == {
        "@types/node": "22.20.5",
        "typescript": "5.9.3",
        "undici-types": "6.21.0",
    }
    assert set(components) == set(expected)
    for name, version in expected.items():
        component = components[name]
        assert component["type"] == "library"
        assert component["version"] == version
        assert component["purl"] == f"pkg:npm/{name.replace('@', '%40')}@{version}"
        assert _props(component)["janus:version_source"] == "lockfile"


# AC4 -----------------------------------------------------------------------


def test_two_runs_are_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    assert _run("--output", str(first)).returncode == 0
    assert _run("--output", str(second)).returncode == 0

    assert _digest(first) == _digest(second)
    assert json.loads(first.read_text())["serialNumber"] == json.loads(
        second.read_text()
    )["serialNumber"]


def test_serial_number_is_a_stable_uuid_and_no_clock_field_is_emitted(
    document: dict[str, Any],
) -> None:
    import uuid

    assert uuid.UUID(_serial_uuid(document))
    assert "timestamp" not in _walk_keys(document)


def test_generator_imports_stay_inside_the_stdlib_allowlist() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])

    assert imported <= STDLIB_ALLOWLIST, f"unexpected imports: {imported - STDLIB_ALLOWLIST}"

    source = SCRIPT.read_text(encoding="utf-8")
    assert "uuid4" not in source
    assert "time.time(" not in source
    assert "datetime.now(" not in source


# AC5 -----------------------------------------------------------------------


def _copy_inputs(tmp_path: Path) -> tuple[Path, Path]:
    pyproject = tmp_path / "pyproject.toml"
    lock = tmp_path / "package-lock.json"
    pyproject.write_bytes(PYPROJECT.read_bytes())
    lock.write_bytes(LOCK.read_bytes())
    return pyproject, lock


def test_identity_tracks_content(tmp_path: Path) -> None:
    pyproject, lock = _copy_inputs(tmp_path)

    def generate(name: str) -> dict[str, Any]:
        output = tmp_path / name
        result = _run(
            "--pyproject",
            str(pyproject),
            "--lock",
            str(lock),
            "--output",
            str(output),
        )
        assert result.returncode == 0, result.stderr
        return json.loads(output.read_text(encoding="utf-8"))

    base = generate("base.json")
    again = generate("again.json")
    assert base["serialNumber"] == again["serialNumber"]
    assert _by_source(base, "lockfile")["typescript"]["version"] == "5.9.3"

    lock.write_text(
        lock.read_text(encoding="utf-8").replace('"version": "5.9.3"', '"version": "5.9.4"'),
        encoding="utf-8",
    )
    bumped = generate("bumped.json")

    assert _by_source(bumped, "lockfile")["typescript"]["version"] == "5.9.4"
    assert bumped["serialNumber"] != base["serialNumber"]


# AC6 -----------------------------------------------------------------------


def test_missing_lockfile_fails_closed(tmp_path: Path) -> None:
    output = tmp_path / "sbom.json"
    missing = tmp_path / "nope" / "package-lock.json"

    result = _run("--lock", str(missing), "--output", str(output))

    assert result.returncode != 0
    assert str(missing) in result.stderr
    assert not output.exists()


def test_malformed_lockfile_fails_closed(tmp_path: Path) -> None:
    pyproject, _ = _copy_inputs(tmp_path)
    broken = tmp_path / "broken-lock.json"
    broken.write_text("{ not json", encoding="utf-8")
    output = tmp_path / "sbom.json"

    result = _run(
        "--pyproject", str(pyproject), "--lock", str(broken), "--output", str(output)
    )

    assert result.returncode != 0
    assert str(broken) in result.stderr
    assert not output.exists()
