"""Content-addressed model artifacts for reproducible forecasts.

A forecast must be reproducible months later, so every fitted model can be
written to a small, offline artifact store. The store is a directory of
canonical JSON documents named by the SHA-256 of their content, not a database
table; nothing here needs a migration.

The artifact records the model card and parameters, the feature values and
their hash, the data snapshot, the code version, and the artifact version. The
prediction ledger keeps referencing an artifact through the existing
``model_version`` column with the convention ``<version>@<artifact_id[:12]>``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Optional, Union

from .. import __version__
from ..analysis.features import features_hash
from ..config import load_settings
from ..memory.models import Prediction, utcnow
from .baseline import LogisticDirectionModel

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX12 = re.compile(r"^[0-9a-f]{12}$")
_ID_PREFIX = re.compile(r"^[0-9a-f]{4,64}$")

class ArtifactNotFoundError(LookupError):
    """Raised when a reference does not resolve to exactly one artifact."""

    def __init__(
        self,
        ref: str,
        root: Union[str, Path],
        candidates: tuple[str, ...] = (),
    ) -> None:
        self.ref = str(ref)
        self.root = Path(root)
        self.candidates = tuple(sorted(candidates))
        message = f"artifact not found: {self.ref} (store: {self.root})"
        if self.candidates:
            message += "; ambiguous: " + ", ".join(self.candidates)
        super().__init__(message)


class ArtifactCorruptError(ValueError):
    """Raised when an artifact file is unreadable or fails its content address."""

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path).absolute()
        super().__init__(f"artifact corrupt: {self.path}")


class FeatureHashMismatchError(ValueError):
    """Raised when features do not match the hash recorded with the artifact."""


@dataclass(frozen=True)
class ModelArtifact:
    """One immutable, content-addressed fitted model."""

    artifact_id: str
    version: str
    created_at: str
    features: dict[str, float]
    features_hash: str
    data_snapshot: Optional[str]
    code_version: str
    card: dict[str, Any]
    params: dict[str, Any]

    @property
    def model(self) -> LogisticDirectionModel:
        """Rebuild the model from the stored parameters and card."""

        payload = dict(self.params)
        payload["card"] = dict(self.card)
        return LogisticDirectionModel.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        """Return the nine persisted fields, without derived state."""

        return {
            "artifact_id": self.artifact_id,
            "version": self.version,
            "created_at": self.created_at,
            "features": self.features,
            "features_hash": self.features_hash,
            "data_snapshot": self.data_snapshot,
            "code_version": self.code_version,
            "card": self.card,
            "params": self.params,
        }


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _identity(
    *,
    version: str,
    features: Mapping[str, float],
    features_hash: str,
    data_snapshot: Optional[str],
    code_version: str,
    card: Mapping[str, Any],
    params: Mapping[str, Any],
) -> dict[str, Any]:
    """The content that determines the artifact id.

    ``created_at`` is deliberately excluded so that saving identical content is
    idempotent and the id stays stable.
    """

    return {
        "version": version,
        "features": dict(features),
        "features_hash": features_hash,
        "data_snapshot": data_snapshot,
        "code_version": code_version,
        "card": dict(card),
        "params": dict(params),
    }


def _content_id(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


class ModelRegistry:
    """A local, content-addressed artifact store.

    ``root`` defaults to ``load_settings().home / "models"``, so ``JANUS_HOME``
    redirects the store. Each artifact is one canonical JSON file named
    ``<artifact_id>.json`` and written with an atomic replace.
    """

    def __init__(self, root: Optional[Union[str, Path]] = None) -> None:
        if root is None:
            root = load_settings().home / "models"
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------
    def save(
        self,
        model: LogisticDirectionModel,
        *,
        version: Optional[str] = None,
        features: Mapping[str, float],
        data_snapshot: Optional[str] = None,
        code_version: Optional[str] = None,
    ) -> ModelArtifact:
        """Persist a fitted model and return its artifact record."""

        if model.card is None:
            raise RuntimeError("model is not fitted")
        payload = model.to_dict()
        card = dict(payload["card"])
        params = {key: value for key, value in payload.items() if key != "card"}
        resolved_version = str(version if version is not None else model.card.version)
        vector = {str(name): float(value) for name, value in dict(features).items()}
        digest = features_hash(vector)
        identity = _identity(
            version=resolved_version,
            features=vector,
            features_hash=digest,
            data_snapshot=data_snapshot,
            code_version=__version__ if code_version is None else str(code_version),
            card=card,
            params=params,
        )
        artifact_id = _content_id(identity)
        artifact = ModelArtifact(
            artifact_id=artifact_id,
            version=resolved_version,
            created_at=utcnow().isoformat(),
            features=vector,
            features_hash=digest,
            data_snapshot=data_snapshot,
            code_version=__version__ if code_version is None else str(code_version),
            card=card,
            params=params,
        )

        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{artifact_id}.json"
        if path.exists():
            # Identical content is already stored; keep its original created_at.
            return self.load(artifact_id)
        self._write_atomic(path, artifact)
        return artifact

    def _write_atomic(self, path: Path, artifact: ModelArtifact) -> None:
        text = _canonical(artifact.to_dict()) + "\n"
        fd, temporary = tempfile.mkstemp(
            dir=self.root,
            prefix=f".{artifact.artifact_id}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def load(self, ref: str) -> ModelArtifact:
        """Resolve a full id, a unique id prefix, or an exact version."""

        reference = str(ref)
        if _ID_PREFIX.fullmatch(reference):
            matches = sorted(
                path for path in self.root.glob("*.json") if path.stem.startswith(reference)
            )
            if len(matches) > 1:
                raise ArtifactNotFoundError(
                    reference, self.root, tuple(path.stem for path in matches)
                )
            if len(matches) == 1:
                return self._read(matches[0])

        by_version = [
            artifact
            for artifact in self._read_all()
            if artifact.version == reference
        ]
        if len(by_version) > 1:
            raise ArtifactNotFoundError(
                reference,
                self.root,
                tuple(artifact.artifact_id for artifact in by_version),
            )
        if len(by_version) == 1:
            return by_version[0]
        raise ArtifactNotFoundError(reference, self.root)

    def list(self) -> List[ModelArtifact]:
        """Return every readable artifact, ordered by creation time and id."""

        artifacts = self._read_all()
        artifacts.sort(key=lambda artifact: (artifact.created_at, artifact.artifact_id))
        return artifacts

    def _read_all(self) -> List[ModelArtifact]:
        artifacts: List[ModelArtifact] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                artifacts.append(self._read(path))
            except ArtifactCorruptError as exc:
                warnings.warn(f"artifact corrupt: {exc.path}", stacklevel=2)
        return artifacts

    def _read(self, path: Path) -> ModelArtifact:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            artifact = ModelArtifact(
                artifact_id=str(payload["artifact_id"]),
                version=str(payload["version"]),
                created_at=str(payload["created_at"]),
                features={
                    str(name): float(value)
                    for name, value in dict(payload["features"]).items()
                },
                features_hash=str(payload["features_hash"]),
                data_snapshot=(
                    None
                    if payload.get("data_snapshot") is None
                    else str(payload["data_snapshot"])
                ),
                code_version=str(payload["code_version"]),
                card=dict(payload["card"]),
                params=dict(payload["params"]),
            )
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            raise ArtifactCorruptError(path) from exc

        if _HEX64.fullmatch(path.stem):
            if artifact.artifact_id != path.stem:
                raise ArtifactCorruptError(path)
            expected = _content_id(
                _identity(
                    version=artifact.version,
                    features=artifact.features,
                    features_hash=artifact.features_hash,
                    data_snapshot=artifact.data_snapshot,
                    code_version=artifact.code_version,
                    card=artifact.card,
                    params=artifact.params,
                )
            )
            if expected != path.stem:
                raise ArtifactCorruptError(path)
        return artifact

    # ------------------------------------------------------------------
    # Replay and ledger linkage
    # ------------------------------------------------------------------
    def replay(
        self,
        ref: Union[str, ModelArtifact],
        *,
        features: Optional[Mapping[str, float]] = None,
    ) -> float:
        """Re-run a stored model and return the stored direction probability."""

        artifact = ref if isinstance(ref, ModelArtifact) else self.load(str(ref))
        if features is not None:
            supplied = {
                str(name): float(value) for name, value in dict(features).items()
            }
            digest = features_hash(supplied)
            if digest != artifact.features_hash:
                raise FeatureHashMismatchError(
                    f"features hash {digest} does not match artifact "
                    f"{artifact.artifact_id} ({artifact.features_hash})"
                )
            values: Mapping[str, float] = supplied
        else:
            values = artifact.features

        model = artifact.model
        vector = [float(values[name]) for name in model.features]
        return float(model.predict_proba([vector])[0])

    def resolve_prediction(self, prediction: Prediction) -> ModelArtifact:
        """Resolve the artifact referenced by ``version@<artifact_id[:12]>``."""

        reference = str(prediction.model_version)
        version, separator, suffix = reference.partition("@")
        if not separator or _HEX12.fullmatch(suffix) is None:
            raise ArtifactNotFoundError(reference, self.root)
        try:
            artifact = self.load(suffix)
        except ArtifactNotFoundError as exc:
            raise ArtifactNotFoundError(
                reference, self.root, exc.candidates
            ) from None
        if artifact.version != version:
            raise ArtifactNotFoundError(reference, self.root)
        if prediction.features_hash != artifact.features_hash:
            raise FeatureHashMismatchError(
                f"prediction features_hash {prediction.features_hash} does not "
                f"match artifact {artifact.artifact_id} ({artifact.features_hash})"
            )
        return artifact


def model_ref(artifact: ModelArtifact) -> str:
    """Return the ledger reference for an artifact: ``<version>@<id[:12]>``."""

    return f"{artifact.version}@{artifact.artifact_id[:12]}"
