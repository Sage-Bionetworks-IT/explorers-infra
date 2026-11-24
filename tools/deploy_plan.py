"""Work out which explorer environments a push to main deploys, and why.

Usage (in CI):
    python -m tools.deploy_plan --base <sha before the push> --head <sha after it>
    python -m tools.deploy_plan --head <sha> --all   # manual run: deploy every target
    python -m tools.deploy_plan --head <sha> --data-import qtl/dev   # manual data import

Writes `matrix` (JSON list of targets) and `has_targets` to $GITHUB_OUTPUT and a
short explanation to $GITHUB_STEP_SUMMARY. Without those variables, prints the
plan as JSON.
"""

import argparse
import json
import logging
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from src.config_loader import (
    AWS_ROLE_ARN_PATTERN,
    BASE_CONFIG_NAME,
    ConfigError,
    merge_config,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEPLOYABLE_TARGETS: tuple[str, ...] = ("qtl/dev",)
CDK_CODE_FILES: tuple[str, ...] = ("app.py", "cdk.json", "pyproject.toml", "uv.lock")
CDK_CODE_DIRS: tuple[str, ...] = ("src/",)
NULL_SHA = "0" * 40
NO_BASE_REASON = "no earlier commit to compare against"
MANUAL_RUN_REASON = "the workflow was run manually"
DATA_IMPORT_REASON = "data import, run manually"


@dataclass(frozen=True)
class TargetPlan:
    target: str
    explorer: str
    environment: str
    aws_role_arn: str
    app: bool
    reason: str


def config_path(target: str) -> str:
    explorer, environment = target.split("/")
    return f"config/{explorer}/{environment}.yaml"


def base_config_path(target: str) -> str:
    explorer, _ = target.split("/")
    return f"config/{explorer}/{BASE_CONFIG_NAME}.yaml"


def aws_role_arn(target: str, config: dict) -> str:
    role_arn = config.get("AWS_ROLE_ARN")
    if not isinstance(role_arn, str) or not AWS_ROLE_ARN_PATTERN.fullmatch(role_arn):
        raise SystemExit(
            f"{config_path(target)} needs an IAM role ARN in AWS_ROLE_ARN."
        )
    return role_arn


def is_cdk_code(path: str) -> bool:
    return path in CDK_CODE_FILES or path.startswith(CDK_CODE_DIRS)


def plan_deploys(
    changed_files: list[str],
    old_configs: dict[str, dict | None],
    new_configs: dict[str, dict | None],
    deploy_all_reason: str | None = None,
) -> list[TargetPlan]:
    """Decide what each deployable target needs.

    With `deploy_all_reason`, every deployable target gets an app deploy for that
    reason, whatever changed.
    """
    cdk_changes = sorted(path for path in changed_files if is_cdk_code(path))
    plans = []
    for target in DEPLOYABLE_TARGETS:
        explorer, environment = target.split("/")
        if new_configs.get(target) is None:
            logger.warning(
                "%s is deployable but %s is missing; skipping it.",
                target,
                config_path(target),
            )
            continue
        if deploy_all_reason:
            reason = deploy_all_reason
        elif cdk_changes:
            reason = f"CDK code changed ({', '.join(cdk_changes)})"
        elif old_configs.get(target) != new_configs[target]:
            config_files = [base_config_path(target), config_path(target)]
            changed = [path for path in config_files if path in changed_files]
            reason = f"{', '.join(changed) or 'its config'} changed"
        else:
            continue
        plans.append(
            TargetPlan(
                target=target,
                explorer=explorer,
                environment=environment,
                aws_role_arn=aws_role_arn(target, new_configs[target]),
                app=True,
                reason=reason,
            )
        )
    return plans


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def commit_exists(sha: str | None, cwd: Path) -> bool:
    if not sha or sha == NULL_SHA:
        return False
    return _git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd).returncode == 0


def changed_files_between(base: str, head: str, cwd: Path) -> list[str]:
    result = _git(["diff", "--name-only", base, head], cwd)
    if result.returncode != 0:
        raise SystemExit(f"git diff {base} {head} failed: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line]


def read_yaml_at(commit: str, path: str, cwd: Path) -> object | None:
    result = _git(["show", f"{commit}:{path}"], cwd)
    if result.returncode != 0:
        return None
    return yaml.safe_load(result.stdout)


def read_config_at(commit: str, target: str, cwd: Path) -> dict | None:
    """Return the target's base.yaml merged with its <env>.yaml, as of `commit`."""
    config = read_yaml_at(commit, config_path(target), cwd)
    if config is None:
        return None
    base = read_yaml_at(commit, base_config_path(target), cwd) or {}
    try:
        return merge_config(base, config, f"{config_path(target)} at {commit}")
    except ConfigError as error:
        raise SystemExit(str(error))


def plan_from_git(
    base: str | None, head: str, cwd: Path, deploy_all: bool = False
) -> list[TargetPlan]:
    compare = not deploy_all and commit_exists(base, cwd)
    if deploy_all:
        deploy_all_reason = MANUAL_RUN_REASON
    elif not compare:
        deploy_all_reason = NO_BASE_REASON
        logger.info("No usable base commit (%s); deploying every target.", base)
    else:
        deploy_all_reason = None
    changed_files = changed_files_between(base, head, cwd) if compare else []
    old_configs = {
        target: read_config_at(base, target, cwd) if compare else None
        for target in DEPLOYABLE_TARGETS
    }
    new_configs = {
        target: read_config_at(head, target, cwd) for target in DEPLOYABLE_TARGETS
    }
    return plan_deploys(
        changed_files, old_configs, new_configs, deploy_all_reason=deploy_all_reason
    )


def plan_data_import(target: str, head: str, cwd: Path) -> list[TargetPlan]:
    """The one target a manual data import runs against, without an app deploy"""
    if target not in DEPLOYABLE_TARGETS:
        raise SystemExit(
            f"{target} isn't deployable. Choose one of {', '.join(DEPLOYABLE_TARGETS)}."
        )
    config = read_config_at(head, target, cwd)
    if config is None:
        raise SystemExit(f"{config_path(target)} doesn't exist at {head}.")
    explorer, environment = target.split("/")
    return [
        TargetPlan(
            target=target,
            explorer=explorer,
            environment=environment,
            aws_role_arn=aws_role_arn(target, config),
            app=False,
            reason=DATA_IMPORT_REASON,
        )
    ]


def summary_lines(plans: list[TargetPlan]) -> list[str]:
    if not plans:
        return ["Nothing to deploy: no deployable target's config or CDK code changed."]
    return [
        (
            f"- **{plan.target}**: app deploy, because {plan.reason}"
            if plan.app
            else f"- **{plan.target}**: {plan.reason}"
        )
        for plan in plans
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="commit before the push")
    parser.add_argument("--head", required=True, help="commit after the push")
    parser.add_argument(
        "--all", action="store_true", help="deploy every deployable target"
    )
    parser.add_argument(
        "--data-import", metavar="TARGET", help="plan a data import for one target"
    )
    args = parser.parse_args()

    if args.data_import:
        plans = plan_data_import(args.data_import, args.head, Path.cwd())
    else:
        plans = plan_from_git(args.base, args.head, Path.cwd(), deploy_all=args.all)
    matrix = json.dumps([asdict(plan) for plan in plans])
    for line in summary_lines(plans):
        logger.info(line)

    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as output:
            output.write(f"matrix={matrix}\n")
            output.write(f"has_targets={'true' if plans else 'false'}\n")
    else:
        print(matrix)

    step_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as summary:
            summary.write("### Deploy plan\n\n")
            summary.write("\n".join(summary_lines(plans)) + "\n")


if __name__ == "__main__":
    main()
