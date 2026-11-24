from pathlib import Path

import pytest
import yaml

from src.explorer_config import (
    BASE_CONFIG_NAME,
    CONFIG_DIR,
    ConfigError,
    ExplorerConfig,
    available_targets,
    load_config,
)

VALID_CONFIG = {
    "AWS_ROLE_ARN": "arn:aws:iam::123456789012:role/example",
    "VPC_CIDR": "10.0.0.0/24",
    "FQDN": "dev.example.org",
    "CERTIFICATE_ID": "certificate-id",
    "TAGS": {"CostCenter": "Example / 000000", "Environment": "dev"},
    "AUTO_SCALE_CAPACITY": {"MIN": 1, "MAX": 2},
    "GTM_CONTAINER_ID": "",
    "APP_VERSION": "edge",
}


def write_config(config_dir: Path, explorer: str, name: str, data) -> None:
    path = config_dir / explorer / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))


@pytest.mark.parametrize("target", available_targets(CONFIG_DIR))
def test_every_committed_config_loads(target):
    explorer, environment = target.split("/")
    config = load_config(explorer, environment)
    assert isinstance(config, ExplorerConfig)
    assert config.tags["Environment"] == environment


def test_base_yaml_is_not_a_target():
    assert not any(
        target.endswith(f"/{BASE_CONFIG_NAME}") for target in available_targets()
    )


def test_qtl_has_a_config_per_environment():
    assert {"qtl/dev", "qtl/stage", "qtl/prod"} <= set(available_targets(CONFIG_DIR))


def test_valid_config_is_parsed(tmp_path):
    write_config(tmp_path, "example", "dev", VALID_CONFIG)
    config = load_config("example", "dev", config_dir=tmp_path)
    assert config.explorer == "example"
    assert config.environment == "dev"
    assert config.aws_role_arn == "arn:aws:iam::123456789012:role/example"
    assert config.auto_scale_capacity.max == 2
    assert config.gtm_enabled is False
    assert config.app_version == "edge"


def test_environment_is_merged_over_base(tmp_path):
    base = {"TAGS": {"CostCenter": "Shared / 000000"}, "GTM_CONTAINER_ID": ""}
    environment = {
        key: value
        for key, value in VALID_CONFIG.items()
        if key not in {"GTM_CONTAINER_ID"}
    }
    environment["TAGS"] = {"Environment": "dev"}
    write_config(tmp_path, "example", BASE_CONFIG_NAME, base)
    write_config(tmp_path, "example", "dev", environment)
    config = load_config("example", "dev", config_dir=tmp_path)
    assert config.tags == {"CostCenter": "Shared / 000000", "Environment": "dev"}
    assert config.gtm_container_id == ""


def test_environment_value_wins_over_base(tmp_path):
    write_config(tmp_path, "example", BASE_CONFIG_NAME, {"APP_VERSION": "1.0.0"})
    write_config(tmp_path, "example", "dev", VALID_CONFIG)
    assert load_config("example", "dev", config_dir=tmp_path).app_version == "edge"


def test_gtm_is_enabled_by_a_container_id(tmp_path):
    write_config(
        tmp_path, "example", "dev", {**VALID_CONFIG, "GTM_CONTAINER_ID": "GTM-ABC123"}
    )
    assert load_config("example", "dev", config_dir=tmp_path).gtm_enabled is True


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
    data = {key: value for key, value in VALID_CONFIG.items() if key != "FQDN"}
    write_config(tmp_path, "example", "dev", data)
    with pytest.raises(ConfigError, match="missing FQDN"):
        load_config("example", "dev", config_dir=tmp_path)


def test_unknown_key_is_rejected(tmp_path):
    data = {**VALID_CONFIG, "APP_VERISON": "1.0.0"}
    write_config(tmp_path, "example", "dev", data)
    with pytest.raises(ConfigError, match="unknown APP_VERISON"):
        load_config("example", "dev", config_dir=tmp_path)


def test_wrong_type_is_rejected(tmp_path):
    data = {**VALID_CONFIG, "AUTO_SCALE_CAPACITY": {"MIN": True, "MAX": 2}}
    write_config(tmp_path, "example", "dev", data)
    with pytest.raises(ConfigError, match="AUTO_SCALE_CAPACITY.MIN must be int"):
        load_config("example", "dev", config_dir=tmp_path)


@pytest.mark.parametrize(
    ("role_arn", "message"),
    [
        (123456789012, "AWS_ROLE_ARN must be str"),
        ("arn:aws:iam::12345:role/example", "IAM role ARN"),
        ("arn:aws:iam::123456789012:user/example", "IAM role ARN"),
        ("123456789012", "IAM role ARN"),
    ],
)
def test_malformed_aws_role_arn_is_rejected(tmp_path, role_arn, message):
    write_config(tmp_path, "example", "dev", {**VALID_CONFIG, "AWS_ROLE_ARN": role_arn})
    with pytest.raises(ConfigError, match=message):
        load_config("example", "dev", config_dir=tmp_path)
