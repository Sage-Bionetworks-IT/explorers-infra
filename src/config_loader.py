"""Load an explorer's settings for one environment from config/<explorer>/.

`base.yaml` holds what every environment shares; `<env>.yaml` is deep-merged over it.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
VALID_ENVIRONMENTS = ("dev", "stage", "prod")
BASE_CONFIG_NAME = "base"
AWS_ROLE_ARN_PATTERN = re.compile(r"arn:aws:iam::\d{12}:role/[\w+=,.@/-]+")

T = TypeVar("T")


class ConfigError(ValueError):
    """Raised when a config file is missing, malformed, or has unexpected keys."""


@dataclass(frozen=True)
class AutoScaleCapacity:
    min: int
    max: int


@dataclass(frozen=True)
class ExplorerConfig:
    explorer: str
    environment: str
    aws_role_arn: str
    vpc_cidr: str
    fqdn: str
    certificate_id: str
    tags: dict[str, str]
    auto_scale_capacity: AutoScaleCapacity
    gtm_container_id: str
    app_version: str

    @property
    def gtm_enabled(self) -> bool:
        return bool(self.gtm_container_id)


def available_targets(config_dir: Path = CONFIG_DIR) -> list[str]:
    """List the `<explorer>/<env>` targets that have a config file."""
    return sorted(
        f"{path.parent.name}/{path.stem}"
        for path in config_dir.glob("*/*.yaml")
        if path.stem in VALID_ENVIRONMENTS
    )


def base_config_path(explorer: str, config_dir: Path = CONFIG_DIR) -> Path:
    return config_dir / explorer / f"{BASE_CONFIG_NAME}.yaml"


def merge_config(base: object, override: object, where: str) -> dict:
    """Deep-merge an environment's settings over the explorer's shared base."""
    merged = dict(_mapping(base, f"{where} (base)"))
    for key, value in _mapping(override, where).items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = merge_config(merged[key], value, f"{where}: {key}")
        else:
            merged[key] = value
    return merged


def load_config(
    explorer: str | None,
    environment: str | None,
    config_dir: Path = CONFIG_DIR,
) -> ExplorerConfig:
    """Read `config/<explorer>/base.yaml` and `<environment>.yaml`, then validate."""
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
    base_path = base_config_path(explorer, config_dir)
    base = yaml.safe_load(base_path.read_text()) if base_path.is_file() else {}

    where = str(path)
    root = merge_config(base, yaml.safe_load(path.read_text()), where)
    _check_keys(
        root,
        {
            "AWS_ROLE_ARN",
            "VPC_CIDR",
            "FQDN",
            "CERTIFICATE_ID",
            "TAGS",
            "AUTO_SCALE_CAPACITY",
            "GTM_CONTAINER_ID",
            "APP_VERSION",
        },
        where,
    )

    tags = _mapping(root["TAGS"], f"{where}: TAGS")
    capacity = _mapping(root["AUTO_SCALE_CAPACITY"], f"{where}: AUTO_SCALE_CAPACITY")
    _check_keys(capacity, {"MIN", "MAX"}, f"{where}: AUTO_SCALE_CAPACITY")

    return ExplorerConfig(
        explorer=explorer,
        environment=environment,
        aws_role_arn=_aws_role_arn(root["AWS_ROLE_ARN"], f"{where}: AWS_ROLE_ARN"),
        vpc_cidr=_typed(root["VPC_CIDR"], str, f"{where}: VPC_CIDR"),
        fqdn=_typed(root["FQDN"], str, f"{where}: FQDN"),
        certificate_id=_typed(root["CERTIFICATE_ID"], str, f"{where}: CERTIFICATE_ID"),
        tags={
            _typed(key, str, f"{where}: TAGS key"): _typed(
                value, str, f"{where}: TAGS.{key}"
            )
            for key, value in tags.items()
        },
        auto_scale_capacity=AutoScaleCapacity(
            min=_typed(capacity["MIN"], int, f"{where}: AUTO_SCALE_CAPACITY.MIN"),
            max=_typed(capacity["MAX"], int, f"{where}: AUTO_SCALE_CAPACITY.MAX"),
        ),
        gtm_container_id=_typed(
            root["GTM_CONTAINER_ID"], str, f"{where}: GTM_CONTAINER_ID"
        ),
        app_version=_typed(root["APP_VERSION"], str, f"{where}: APP_VERSION"),
    )


def _aws_role_arn(value: object, where: str) -> str:
    role_arn = _typed(value, str, where)
    if not AWS_ROLE_ARN_PATTERN.fullmatch(role_arn):
        raise ConfigError(
            f"{where} must be an IAM role ARN like arn:aws:iam::<12 digits>:role/<name>."
        )
    return role_arn


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
