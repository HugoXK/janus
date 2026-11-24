from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:  # pragma: no cover - optional fallback
        tomllib = None  # type: ignore[assignment]

PROVIDER_ENV = {
    "tiingo_api_key": "TIINGO_API_KEY",
    "fred_api_key": "FRED_API_KEY",
    "newsapi_api_key": "NEWSAPI_API_KEY",
    "marketaux_api_key": "MARKETAUX_API_KEY",
    "sec_user_agent": "SEC_USER_AGENT",
}

LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    critical: bool = True


@dataclass(frozen=True)
class Settings:
    """Local-first settings.

    Precedence is: CLI overrides > environment variables > config file >
    defaults. Provider keys are kept out of ``repr`` and are masked by
    ``redacted()``.
    """

    home: Path = Path.home() / ".janus"
    db_path: Optional[Path] = None
    timezone: str = "UTC"
    log_level: str = "INFO"
    providers: dict[str, str] = field(default_factory=dict, repr=False)
    data: dict[str, Any] = field(default_factory=dict)
    config_path: Optional[Path] = None

    @property
    def database(self) -> str:
        return str(self.db_path) if self.db_path is not None else str(self.home / "janus.db")

    def ensure_home(self) -> Path:
        self.home.mkdir(parents=True, exist_ok=True)
        return self.home

    def redacted(self) -> dict[str, Any]:
        return {
            "home": str(self.home),
            "database": self.database,
            "timezone": self.timezone,
            "log_level": self.log_level,
            "config_path": str(self.config_path) if self.config_path else None,
            "providers": {
                key: ("***" if value else "") for key, value in self.providers.items()
            },
            "data": self.data,
        }

    def doctor(self) -> list[Check]:
        checks: list[Check] = []
        checks.append(
            Check(
                "home",
                _writable(self.home),
                f"{self.home} (writable: {_writable(self.home)})",
            )
        )
        db_parent = self.db_path.parent if self.db_path else self.home
        checks.append(
            Check(
                "database",
                _writable(db_parent),
                f"{self.database} (parent writable: {_writable(db_parent)})",
            )
        )

        try:
            ZoneInfo(self.timezone)
            timezone_ok = True
            timezone_detail = self.timezone
        except ZoneInfoNotFoundError:
            timezone_ok = False
            timezone_detail = f"unknown timezone: {self.timezone}"
        checks.append(Check("timezone", timezone_ok, timezone_detail))

        checks.append(
            Check(
                "clock",
                True,
                datetime.now(timezone.utc).isoformat(),
            )
        )

        if self.config_path is None:
            checks.append(Check("config", True, "no config file requested", critical=False))
        elif self.config_path.exists():
            checks.append(Check("config", True, str(self.config_path), critical=False))
        else:
            checks.append(
                Check(
                    "config",
                    False,
                    f"not found: {self.config_path}",
                    critical=False,
                )
            )

        for provider, env_name in PROVIDER_ENV.items():
            present = bool(self.providers.get(provider))
            checks.append(
                Check(
                    f"provider:{provider}",
                    present,
                    "configured" if present else f"set {env_name}",
                    critical=False,
                )
            )
        return checks


def _writable(path: Path) -> bool:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return os.access(current, os.W_OK)


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if tomllib is None:  # pragma: no cover - only on minimal Python builds
        raise RuntimeError(
            "TOML config requires Python 3.11+ or the 'tomli' package"
        )
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_settings(
    config_path: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    overrides: Optional[Mapping[str, Any]] = None,
) -> Settings:
    """Load settings with deterministic precedence."""

    environment = os.environ if env is None else env
    overrides = dict(overrides or {})

    default_home = Path(environment.get("JANUS_HOME", Path.home() / ".janus")).expanduser()
    candidate_config = Path(
        config_path
        or environment.get("JANUS_CONFIG", default_home / "config.toml")
    ).expanduser()
    raw = _load_toml(candidate_config)

    def pick(key: str, env_key: str, default: Any) -> Any:
        if key in overrides:
            return overrides[key]
        if env_key in environment:
            return environment[env_key]
        if key in raw:
            return raw[key]
        return default

    home = Path(pick("home", "JANUS_HOME", default_home)).expanduser()
    db_raw = pick("db_path", "JANUS_DB", raw.get("db_path"))
    db_path = Path(db_raw).expanduser() if db_raw else None
    timezone_name = str(pick("timezone", "JANUS_TIMEZONE", "UTC"))
    log_level = str(pick("log_level", "JANUS_LOG_LEVEL", "INFO")).upper()

    providers = {
        key: str(value)
        for key, value in dict(raw.get("providers", {})).items()
        if value is not None
    }
    for key, env_name in PROVIDER_ENV.items():
        if env_name in environment:
            providers[key] = environment[env_name]
    if "providers" in overrides:
        providers.update(
            {key: str(value) for key, value in dict(overrides["providers"]).items()}
        )

    data = dict(raw.get("data", {}))
    if "data" in overrides:
        data.update(dict(overrides["data"]))

    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {timezone_name}") from exc
    if log_level not in LOG_LEVELS:
        raise ValueError(
            f"invalid log level: {log_level}; expected one of {sorted(LOG_LEVELS)}"
        )

    return Settings(
        home=home,
        db_path=db_path,
        timezone=timezone_name,
        log_level=log_level,
        providers=providers,
        data=data,
        config_path=candidate_config,
    )


DEFAULT_SETTINGS = Settings()
