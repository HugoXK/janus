"""Envelope encryption at rest: master key -> wrapped data keys -> records.

Threat boundary
---------------
The key-encryption key (KEK) is read only from ``JANUS_MASTER_KEY`` or a
``0600`` file (``JANUS_MASTER_KEY_FILE`` or ``$JANUS_HOME/keys/master.key``).
Data-encryption keys (DEKs) are random per key id, stored *wrapped* by the KEK
in the store's ``encryption_key`` table, and never written in the clear.

Every ciphertext record names its ``key_id``. Reads fail closed with a typed
error (``key_missing``, ``key_mismatch``, ``ciphertext_invalid``); nothing ever
falls back to plaintext or an empty value.

Ciphertext format: ``janus1.<key_id>.<nonce>.<ciphertext+tag>``.
Wrapped DEK format: ``januswrap1.<nonce>.<ciphertext+tag>``.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

def _load_aesgcm() -> Any:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:  # pragma: no cover - exercised only on a broken install
        return None
    return AESGCM


AESGCM: Any = _load_aesgcm()

ENV_MASTER_KEY = "JANUS_MASTER_KEY"
ENV_MASTER_KEY_FILE = "JANUS_MASTER_KEY_FILE"
DEFAULT_JANUS_HOME = Path("~/.janus")
DEFAULT_KEY_FILE = Path("keys/master.key")
TOKEN_PREFIX = "janus1"
WRAP_PREFIX = "januswrap1"
KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class EncryptionError(Exception):
    """Base class for every encryption-at-rest failure."""

    code = "encryption_error"


class KeyMissingError(EncryptionError):
    """No key is configured, or an encrypted store was opened without one."""

    code = "key_missing"


class KeyMismatchError(EncryptionError):
    """A ciphertext names a key id the store does not hold, or the KEK is wrong."""

    code = "key_mismatch"


class CiphertextInvalidError(EncryptionError):
    """Authentication failed: tampered, truncated, or context-swapped data."""

    code = "ciphertext_invalid"


class KeyConfigError(EncryptionError):
    """Key material is present but malformed (length, base64, permissions)."""

    code = "key_invalid"


class KeyInUseError(EncryptionError):
    """A key cannot be retired while rows still reference it."""

    code = "key_in_use"


class EncryptionRequiredError(EncryptionError):
    """An operation needs an encrypted store but found plaintext rows."""

    code = "encryption_required"


class CryptoUnavailableError(EncryptionError):
    """The ``cryptography`` dependency is missing; refuse to store plaintext."""

    code = "crypto_unavailable"


class PlaintextBlobError(EncryptionError):
    """A blob is still plaintext while an encrypted store expects sealed data."""

    code = "plaintext_blob"


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str, *, error: type[EncryptionError], detail: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise error(detail) from exc


def _require_aesgcm() -> Any:
    if AESGCM is None:  # pragma: no cover - depends on the install
        raise CryptoUnavailableError(
            "encryption at rest needs the 'cryptography' dependency, which is "
            "declared in pyproject.toml but missing from this install"
        )
    return AESGCM


def load_master_key(environ: Optional[Mapping[str, str]] = None) -> bytes:
    """Load the 32-byte KEK from the environment or a ``0600`` file."""

    environ = os.environ if environ is None else environ
    encoded = environ.get(ENV_MASTER_KEY)
    if encoded:
        return _decode_master_key(encoded, ENV_MASTER_KEY)

    key_file = environ.get(ENV_MASTER_KEY_FILE)
    if not key_file:
        default_home = Path(environ.get("JANUS_HOME", str(DEFAULT_JANUS_HOME))).expanduser()
        candidate = default_home / DEFAULT_KEY_FILE
        if not candidate.exists():
            raise KeyMissingError(
                f"no master key configured; set {ENV_MASTER_KEY} or point "
                f"{ENV_MASTER_KEY_FILE} at a 0600 file (for example {candidate})"
            )
        key_file = str(candidate)

    path = Path(key_file)
    try:
        mode = path.stat().st_mode
    except FileNotFoundError as exc:
        raise KeyConfigError(f"master key file {path} does not exist") from exc
    if os.name == "posix" and mode & 0o077:
        raise KeyConfigError(
            f"master key file {path} has unsafe permission bits; run chmod 600"
        )
    try:
        encoded = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise KeyConfigError(f"cannot read master key file {path}") from exc
    return _decode_master_key(encoded, str(path))


def _decode_master_key(encoded: str, source: str) -> bytes:
    material = _b64decode(
        encoded.strip(),
        error=KeyConfigError,
        detail=f"master key from {source} is not valid base64",
    )
    if len(material) != KEY_BYTES:
        raise KeyConfigError(
            f"master key from {source} must be {KEY_BYTES} bytes, got {len(material)}"
        )
    return material


@dataclass(frozen=True)
class WrappedKey:
    key_id: str
    state: str


class KeyManager:
    """Manage wrapped DEKs in the store's ``encryption_key`` table."""

    def __init__(self, connection: Any, master_key: bytes) -> None:
        _require_aesgcm()
        if len(master_key) != KEY_BYTES:
            raise KeyConfigError(
                f"master key must be {KEY_BYTES} bytes, got {len(master_key)}"
            )
        self._conn = connection
        self._master = bytes(master_key)
        self._dek_cache: dict[str, bytes] = {}

    # -- key inventory ---------------------------------------------------
    def keys(self) -> list[WrappedKey]:
        rows = self._conn.execute(
            "SELECT key_id, state FROM encryption_key ORDER BY key_id"
        ).fetchall()
        return [WrappedKey(key_id=str(row[0]), state=str(row[1])) for row in rows]

    @property
    def active_key_id(self) -> Optional[str]:
        row = self._conn.execute(
            "SELECT key_id FROM encryption_key WHERE state = 'active' ORDER BY key_id LIMIT 1"
        ).fetchone()
        return str(row[0]) if row else None

    def ensure_key(self) -> str:
        active = self.active_key_id
        if active is not None:
            return active
        key_id = self._next_key_id()
        wrapped = self._wrap(os.urandom(KEY_BYTES), key_id)
        self._conn.execute(
            "INSERT INTO encryption_key (key_id, wrapped_dek, state, created_at) "
            "VALUES (?, ?, 'active', ?)",
            (key_id, wrapped, _now()),
        )
        self._conn.commit()
        return key_id

    def dek(self, key_id: str) -> bytes:
        cached = self._dek_cache.get(key_id)
        if cached is not None:
            return cached
        row = self._conn.execute(
            "SELECT wrapped_dek FROM encryption_key WHERE key_id = ?", (key_id,)
        ).fetchone()
        if row is None:
            known = ", ".join(key.key_id for key in self.keys()) or "(none)"
            raise KeyMismatchError(
                f"record needs key {key_id!r}, which this store does not hold "
                f"(available: {known})"
            )
        material = self._unwrap(str(row[0]), key_id)
        self._dek_cache[key_id] = material
        return material

    def start_rotation(self) -> str:
        """Create a new active key id; the previous one stays for decryption."""

        current = self.active_key_id
        if current is None:
            return self.ensure_key()
        new_id = self._next_key_id()
        self._conn.execute(
            "UPDATE encryption_key SET state = 'retired', retired_at = ? WHERE key_id = ?",
            (_now(), current),
        )
        self._conn.execute(
            "INSERT INTO encryption_key (key_id, wrapped_dek, state, created_at) "
            "VALUES (?, ?, 'active', ?)",
            (new_id, self._wrap(os.urandom(KEY_BYTES), new_id), _now()),
        )
        self._conn.commit()
        return new_id

    def retire(self, key_id: str) -> None:
        state = self._conn.execute(
            "SELECT state FROM encryption_key WHERE key_id = ?", (key_id,)
        ).fetchone()
        if state is None:
            raise KeyMismatchError(f"key {key_id!r} is not held by this store")
        if str(state[0]) == "active":
            raise KeyInUseError(f"key {key_id!r} is active and cannot be retired")
        self._conn.execute("DELETE FROM encryption_key WHERE key_id = ?", (key_id,))
        self._conn.commit()
        self._dek_cache.pop(key_id, None)

    # -- wrapping --------------------------------------------------------
    def _wrap(self, dek: bytes, key_id: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = _require_aesgcm()(self._master).encrypt(
            nonce, dek, _wrap_aad(key_id)
        )
        return ".".join([WRAP_PREFIX, _b64encode(nonce), _b64encode(ciphertext)])

    def _unwrap(self, wrapped: str, key_id: str) -> bytes:
        parts = wrapped.split(".")
        if len(parts) != 3 or parts[0] != WRAP_PREFIX:
            raise KeyMismatchError("stored data key is not in the wrapped-key envelope")
        nonce = _b64decode(
            parts[1], error=KeyMismatchError, detail="wrapped key nonce is invalid"
        )
        ciphertext = _b64decode(
            parts[2], error=KeyMismatchError, detail="wrapped key ciphertext is invalid"
        )
        try:
            return _require_aesgcm()(self._master).decrypt(
                nonce, ciphertext, _wrap_aad(key_id)
            )
        except EncryptionError:
            raise
        except Exception as exc:
            raise KeyMismatchError(
                "the configured master key cannot unwrap this store's data keys"
            ) from exc

    def _next_key_id(self) -> str:
        highest = 0
        for key in self.keys():
            match = re.fullmatch(r"k(\d+)", key.key_id)
            if match:
                highest = max(highest, int(match.group(1)))
        return f"k{highest + 1}"


class Sealer:
    """Seal and unseal record fields with the active DEK, binding a context."""

    def __init__(self, manager: KeyManager) -> None:
        _require_aesgcm()
        self.manager = manager

    @property
    def active_key_id(self) -> str:
        active = self.manager.active_key_id
        if active is None:
            raise KeyMissingError("the store has no active data key; run 'janus keys init'")
        return active

    def seal(self, plaintext: bytes, *, context: str = "") -> str:
        key_id = self.active_key_id
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = _require_aesgcm()(self.manager.dek(key_id)).encrypt(
            nonce, bytes(plaintext), _aad(context)
        )
        return ".".join([TOKEN_PREFIX, key_id, _b64encode(nonce), _b64encode(ciphertext)])

    def unseal(self, token: str, *, context: str = "") -> bytes:
        key_id, nonce, ciphertext = self._parse(token)
        try:
            return _require_aesgcm()(self.manager.dek(key_id)).decrypt(
                nonce, ciphertext, _aad(context)
            )
        except EncryptionError:
            raise
        except Exception as exc:
            raise CiphertextInvalidError(
                f"cannot decrypt value sealed with key {key_id!r}: "
                "wrong context or tampered ciphertext"
            ) from exc

    def rotate(self, token: str, *, context: str = "") -> str:
        return self.seal(self.unseal(token, context=context), context=context)

    def needs_rotation(self, token: str) -> bool:
        return self.key_id_of(token) != self.active_key_id

    @staticmethod
    def is_sealed(value: str | bytes) -> bool:
        raw = value.decode("ascii", "replace") if isinstance(value, bytes) else value
        return isinstance(raw, str) and raw.startswith(f"{TOKEN_PREFIX}.") and raw.count(".") == 3

    def key_id_of(self, token: str) -> str:
        return self._parse(token)[0]

    @staticmethod
    def _aad(context: str) -> bytes:
        return _aad(context)

    @staticmethod
    def _parse(token: str) -> tuple[str, bytes, bytes]:
        if not isinstance(token, str) or not token:
            raise CiphertextInvalidError("sealed value must be a non-empty string")
        parts = token.split(".")
        if len(parts) != 4:
            raise CiphertextInvalidError("sealed value must have four dot-separated parts")
        prefix, key_id, nonce_text, ciphertext_text = parts
        if prefix != TOKEN_PREFIX:
            raise CiphertextInvalidError(f"unsupported sealed value prefix {prefix!r}")
        if not _KEY_ID.match(key_id):
            raise CiphertextInvalidError("sealed value has an invalid key id")
        nonce = _b64decode(
            nonce_text, error=CiphertextInvalidError, detail="sealed value has an invalid nonce"
        )
        ciphertext = _b64decode(
            ciphertext_text,
            error=CiphertextInvalidError,
            detail="sealed value has an invalid ciphertext",
        )
        if len(nonce) != NONCE_BYTES:
            raise CiphertextInvalidError(f"sealed value nonce must be {NONCE_BYTES} bytes")
        if len(ciphertext) < TAG_BYTES:
            raise CiphertextInvalidError("sealed value ciphertext is too short")
        return key_id, nonce, ciphertext


def _aad(context: str) -> bytes:
    return f"{TOKEN_PREFIX}|{context}".encode("utf-8")


def _wrap_aad(key_id: str) -> bytes:
    return f"{WRAP_PREFIX}|{key_id}".encode("utf-8")


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def field_context(table: str, row_id: str, column: str) -> str:
    """Bind a ciphertext to exactly one table/row/column."""

    return f"{table}.{column}:{row_id}"


def encrypted_columns() -> dict[str, tuple[str, ...]]:
    """Columns that must never be written in plaintext, per table."""

    return {
        "thesis": ("statement", "assumptions", "catalysts", "risks", "falsifiers"),
        "prediction": ("target",),
        "outcome": ("realized_value",),
    }
