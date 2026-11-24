from pathlib import Path

import pytest
import yaml

from src.explorer_config import (
    CONFIG_DIR,
    ConfigError,
    ExplorerConfig,
    available_targets,
    load_config,
)

VALID_CONFIG = {
    "aws_role_arn": "arn:aws:iam::123456789012:role/example",
    "vpc_cidr": "10.0.0.0/24",
    "fqdn": "dev.example.org",
    "certificate_id": "certificate-id",
    "tags": {"CostCenter": "Example / 000000", "Environment": "dev"},
    "autoscale": {"min": 1, "max": 2},
    "google_tag_manager": {"enabled": False, "container_id": ""},
    "app": {"version": "edge"},
}


def write_config(config_dir: Path, explorer: str, environment: str, data) -> None:
    path = config_dir / explorer / f"{environment}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))


@pytest.mark.parametrize("target", available_targets(CONFIG_DIR))
def test_every_committed_config_loads(target):
    explorer, environment = target.split("/")
    config = load_config(explorer, environment)
    assert isinstance(config, ExplorerConfig)
    assert config.tags["Environment"] == environment


def test_qtl_has_a_config_per_environment():
    assert {"qtl/dev", "qtl/stage", "qtl/prod"} <= set(available_targets(CONFIG_DIR))


def test_valid_config_is_parsed(tmp_path):
    write_config(tmp_path, "example", "dev", VALID_CONFIG)
    config = load_config("example", "dev", config_dir=tmp_path)
    assert config.explorer == "example"
    assert config.environment == "dev"
    assert config.aws_role_arn == "arn:aws:iam::123456789012:role/example"
    assert config.autoscale.max == 2
    assert config.google_tag_manager.enabled is False
    assert config.app.version == "edge"


@pytest.mark.parametrize(
    ("explorer", "environment"), [(None, "dev"), ("example", None), ("", "")]
)
def test_missing_explorer_or_environment_is_rejected(tmp_path, explorer, environment):
    with pytest.raises(ConfigError, match="EXPLORER"):
        load_config(explorer, environment, config_dir=tmp_path)


def test_unknown_environment_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="ENV must be one of"):
        load_config("example", "qa", config_dir=tmp_path)


def test_missing_file_lists_available_targets(tmp_path):
    write_config(tmp_path, "example", "dev", VALID_CONFIG)
    with pytest.raises(ConfigError, match="Available targets: example/dev"):
        load_config("example", "prod", config_dir=tmp_path)


def test_missing_key_is_rejected(tmp_path):
    data = {key: value for key, value in VALID_CONFIG.items() if key != "fqdn"}
    write_config(tmp_path, "example", "dev", data)
    with pytest.raises(ConfigError, match="missing fqdn"):
        load_config("example", "dev", config_dir=tmp_path)


def test_unknown_key_is_rejected(tmp_path):
    data = {**VALID_CONFIG, "app": {"version": "edge", "verison": "1.0.0"}}
    write_config(tmp_path, "example", "dev", data)
    with pytest.raises(ConfigError, match="unknown verison"):
        load_config("example", "dev", config_dir=tmp_path)


def test_wrong_type_is_rejected(tmp_path):
    data = {**VALID_CONFIG, "autoscale": {"min": True, "max": 2}}
    write_config(tmp_path, "example", "dev", data)
    with pytest.raises(ConfigError, match="autoscale.min must be int"):
        load_config("example", "dev", config_dir=tmp_path)


@pytest.mark.parametrize(
    ("role_arn", "message"),
    [
        (123456789012, "aws_role_arn must be str"),
        ("arn:aws:iam::12345:role/example", "IAM role ARN"),
        ("arn:aws:iam::123456789012:user/example", "IAM role ARN"),
        ("123456789012", "IAM role ARN"),
    ],
)
def test_malformed_aws_role_arn_is_rejected(tmp_path, role_arn, message):
    write_config(tmp_path, "example", "dev", {**VALID_CONFIG, "aws_role_arn": role_arn})
    with pytest.raises(ConfigError, match=message):
        load_config("example", "dev", config_dir=tmp_path)
