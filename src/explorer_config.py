"""Load an explorer's settings for one environment from config/<explorer>/<env>.yaml."""

from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
VALID_ENVIRONMENTS = ("dev", "stage", "prod")

T = TypeVar("T")


class ConfigError(ValueError):
    """Raised when a config file is missing, malformed, or has unexpected keys."""


@dataclass(frozen=True)
class AutoScale:
    min: int
    max: int


@dataclass(frozen=True)
class GoogleTagManager:
    enabled: bool
    container_id: str


@dataclass(frozen=True)
class AppRelease:
    version: str


@dataclass(frozen=True)
class ExplorerConfig:
    explorer: str
    environment: str
    vpc_cidr: str
    fqdn: str
    certificate_id: str
    tags: dict[str, str]
    autoscale: AutoScale
    google_tag_manager: GoogleTagManager
    app: AppRelease


def available_targets(config_dir: Path = CONFIG_DIR) -> list[str]:
    """List the `<explorer>/<env>` targets that have a config file."""
    return sorted(
        f"{path.parent.name}/{path.stem}" for path in config_dir.glob("*/*.yaml")
    )


def load_config(
    explorer: str | None,
    environment: str | None,
    config_dir: Path = CONFIG_DIR,
) -> ExplorerConfig:
    """Read and validate `config/<explorer>/<environment>.yaml`."""
    if not explorer or not environment:
        raise ConfigError(
            "Must set environment variables `EXPLORER` and `ENV`. "
            f"Currently EXPLORER={explorer!r}, ENV={environment!r}."
        )
    if environment not in VALID_ENVIRONMENTS:
        raise ConfigError(
            f"ENV must be one of {', '.join(VALID_ENVIRONMENTS)}. "
            f"Currently set to {environment!r}."
        )
    path = config_dir / explorer / f"{environment}.yaml"
    if not path.is_file():
        targets = ", ".join(available_targets(config_dir)) or "none"
        raise ConfigError(
            f"No config file for {explorer}/{environment} at {path}. "
            f"Available targets: {targets}."
        )

    raw = yaml.safe_load(path.read_text())
    where = str(path)
    root = _mapping(raw, where)
    _check_keys(
        root,
        {
            "vpc_cidr",
            "fqdn",
            "certificate_id",
            "tags",
            "autoscale",
            "google_tag_manager",
            "app",
        },
        where,
    )

    tags = _mapping(root["tags"], f"{where}: tags")
    autoscale = _mapping(root["autoscale"], f"{where}: autoscale")
    _check_keys(autoscale, {"min", "max"}, f"{where}: autoscale")
    google_tag_manager = _mapping(
        root["google_tag_manager"], f"{where}: google_tag_manager"
    )
    _check_keys(
        google_tag_manager, {"enabled", "container_id"}, f"{where}: google_tag_manager"
    )
    app = _mapping(root["app"], f"{where}: app")
    _check_keys(app, {"version"}, f"{where}: app")

    return ExplorerConfig(
        explorer=explorer,
        environment=environment,
        vpc_cidr=_typed(root["vpc_cidr"], str, f"{where}: vpc_cidr"),
        fqdn=_typed(root["fqdn"], str, f"{where}: fqdn"),
        certificate_id=_typed(root["certificate_id"], str, f"{where}: certificate_id"),
        tags={
            _typed(key, str, f"{where}: tags key"): _typed(
                value, str, f"{where}: tags.{key}"
            )
            for key, value in tags.items()
        },
        autoscale=AutoScale(
            min=_typed(autoscale["min"], int, f"{where}: autoscale.min"),
            max=_typed(autoscale["max"], int, f"{where}: autoscale.max"),
        ),
        google_tag_manager=GoogleTagManager(
            enabled=_typed(
                google_tag_manager["enabled"],
                bool,
                f"{where}: google_tag_manager.enabled",
            ),
            container_id=_typed(
                google_tag_manager["container_id"],
                str,
                f"{where}: google_tag_manager.container_id",
            ),
        ),
        app=AppRelease(version=_typed(app["version"], str, f"{where}: app.version")),
    )


def _mapping(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping, got {type(value).__name__}.")
    return value


def _check_keys(mapping: dict, expected: set[str], where: str) -> None:
    missing = sorted(expected - mapping.keys())
    unknown = sorted(mapping.keys() - expected)
    problems = []
    if missing:
        problems.append(f"missing {', '.join(missing)}")
    if unknown:
        problems.append(f"unknown {', '.join(unknown)}")
    if problems:
        raise ConfigError(f"{where}: {'; '.join(problems)}.")


def _typed(value: object, expected: type[T], where: str) -> T:
    # bool is a subclass of int, so `True` must not pass as an int.
    if isinstance(value, bool) and expected is not bool:
        raise ConfigError(f"{where} must be {expected.__name__}, got bool.")
    if not isinstance(value, expected):
        raise ConfigError(
            f"{where} must be {expected.__name__}, got {type(value).__name__}."
        )
    return value
