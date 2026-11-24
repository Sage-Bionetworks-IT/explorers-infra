import subprocess
from pathlib import Path

import pytest
import yaml

from tools.deploy_plan import (
    DEPLOYABLE_TARGETS,
    MANUAL_RUN_REASON,
    NO_BASE_REASON,
    base_config_path,
    NULL_SHA,
    config_path,
    plan_deploys,
    plan_from_git,
    summary_lines,
)

TARGET = "qtl/dev"
CONFIG = {
    "AWS_ROLE_ARN": "arn:aws:iam::123456789012:role/example",
    "FQDN": "dev.example.org",
    "APP_VERSION": "edge",
}


def configs(config: dict | None) -> dict[str, dict | None]:
    return {target: config for target in DEPLOYABLE_TARGETS}


def test_qtl_dev_is_the_only_deployable_target():
    assert DEPLOYABLE_TARGETS == ("qtl/dev",)


def test_config_change_deploys_that_target():
    new = {**CONFIG, "APP_VERSION": "1.2.0"}
    plans = plan_deploys([config_path(TARGET)], configs(CONFIG), configs(new))
    assert [plan.target for plan in plans] == [TARGET]
    assert plans[0].app is True
    assert plans[0].aws_role_arn == CONFIG["AWS_ROLE_ARN"]
    assert plans[0].reason == f"{config_path(TARGET)} changed"


def test_data_only_change_does_not_deploy_the_app():
    old = {**CONFIG, "DATA": {"DATA_VERSION": 1}}
    new = {**CONFIG, "DATA": {"DATA_VERSION": 2}}
    assert plan_deploys([config_path(TARGET)], configs(old), configs(new)) == []


@pytest.mark.parametrize(
    "path", ["app.py", "cdk.json", "pyproject.toml", "uv.lock", "src/service_stack.py"]
)
def test_cdk_code_change_deploys_every_target(path):
    plans = plan_deploys([path], configs(CONFIG), configs(CONFIG))
    assert [plan.target for plan in plans] == list(DEPLOYABLE_TARGETS)
    assert path in plans[0].reason


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "tests/unit/test_deploy_plan.py",
        "tools/deploy_plan.py",
        ".github/workflows/deploy.yaml",
        "config/qtl/stage.yaml",
    ],
)
def test_other_changes_deploy_nothing(path):
    assert plan_deploys([path], configs(CONFIG), configs(CONFIG)) == []


def test_without_a_base_commit_every_target_deploys():
    plans = plan_deploys(
        [], configs(None), configs(CONFIG), deploy_all_reason=NO_BASE_REASON
    )
    assert [plan.target for plan in plans] == list(DEPLOYABLE_TARGETS)
    assert plans[0].reason == NO_BASE_REASON


def test_target_without_a_config_file_is_skipped():
    assert plan_deploys(["app.py"], configs(CONFIG), configs(None)) == []


def test_summary_explains_each_target_and_the_empty_case():
    plans = plan_deploys(["app.py"], configs(CONFIG), configs(CONFIG))
    assert summary_lines(plans) == [
        f"- **{TARGET}**: app deploy, because CDK code changed (app.py)"
    ]
    assert summary_lines([])[0].startswith("Nothing to deploy")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit_config(
    repo: Path, config: dict, message: str, path: str = config_path(TARGET)
) -> str:
    path = repo / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config))
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.org")
    git(tmp_path, "config", "user.name", "Test")
    return tmp_path


def test_plan_from_git_reads_configs_at_both_commits(repo):
    base = commit_config(repo, CONFIG, "base")
    head = commit_config(repo, {**CONFIG, "APP_VERSION": "1.2.0"}, "bump")
    plans = plan_from_git(base, head, repo)
    assert [plan.target for plan in plans] == [TARGET]


def test_plan_from_git_deploys_the_target_when_its_base_yaml_changes(repo):
    env_config = {key: value for key, value in CONFIG.items() if key != "FQDN"}
    commit_config(repo, env_config, "env")
    base = commit_config(
        repo, {"FQDN": "dev.example.org"}, "base", base_config_path(TARGET)
    )
    head = commit_config(
        repo, {"FQDN": "new.example.org"}, "move", base_config_path(TARGET)
    )
    plans = plan_from_git(base, head, repo)
    assert [plan.target for plan in plans] == [TARGET]
    assert plans[0].reason == f"{base_config_path(TARGET)} changed"


def test_plan_from_git_ignores_a_base_value_the_environment_overrides(repo):
    commit_config(repo, CONFIG, "env")
    base = commit_config(
        repo, {"FQDN": "a.example.org"}, "base", base_config_path(TARGET)
    )
    head = commit_config(
        repo, {"FQDN": "b.example.org"}, "base", base_config_path(TARGET)
    )
    assert plan_from_git(base, head, repo) == []


def test_plan_from_git_with_unchanged_config_deploys_nothing(repo):
    base = commit_config(repo, CONFIG, "base")
    (repo / "README.md").write_text("docs")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "docs")
    assert plan_from_git(base, git(repo, "rev-parse", "HEAD"), repo) == []


@pytest.mark.parametrize("base", [None, NULL_SHA, "1234567890abcdef"])
def test_plan_from_git_without_a_usable_base_deploys_everything(repo, base):
    head = commit_config(repo, CONFIG, "first")
    plans = plan_from_git(base, head, repo)
    assert [plan.target for plan in plans] == [TARGET]


@pytest.mark.parametrize(
    "role_arn", [None, 123456789012, "arn:aws:iam::12345:role/example"]
)
def test_missing_or_malformed_role_arn_stops_the_plan(role_arn):
    config = {**CONFIG, "AWS_ROLE_ARN": role_arn}
    with pytest.raises(SystemExit, match="AWS_ROLE_ARN"):
        plan_deploys(["app.py"], configs(config), configs(config))


def test_manual_run_deploys_every_target_even_when_nothing_changed(repo):
    base = commit_config(repo, CONFIG, "base")
    (repo / "README.md").write_text("docs")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "docs")
    head = git(repo, "rev-parse", "HEAD")
    plans = plan_from_git(base, head, repo, deploy_all=True)
    assert [plan.target for plan in plans] == [TARGET]
    assert plans[0].reason == MANUAL_RUN_REASON
