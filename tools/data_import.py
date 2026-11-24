"""Run one data import as a Fargate task and follow it until it stops.

Usage (in CI, with AWS credentials for the target's account):
    python -m tools.data_import --explorer qtl --environment dev

Reads the task, network and log settings from the `<explorer>-<env>-data-import`
stack's outputs, refuses to start while another import of that environment is
running, then starts the task, prints its log, and exits with 0 only if the
loader succeeded. The task ARN goes to $GITHUB_OUTPUT as soon as the task
starts, so a cancelled run can still stop it.
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import boto3

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_REGION = "us-east-1"
POLL_SECONDS = 15
STOPPED = "STOPPED"
CANCEL_REASON = "The GitHub Actions run that started this import was cancelled"
# ECS rejects a longer startedBy value.
STARTED_BY_MAX_LENGTH = 36
REQUIRED_OUTPUTS = (
    "ClusterName",
    "TaskDefinitionFamily",
    "SubnetIds",
    "SecurityGroupId",
    "LogGroupName",
    "ContainerName",
)


@dataclass(frozen=True)
class ImportStack:
    cluster: str
    family: str
    subnet_ids: list[str]
    security_group_id: str
    log_group: str
    container: str


@dataclass(frozen=True)
class ImportResult:
    exit_code: int | None
    stopped_reason: str
    container_reason: str | None

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


def stack_name(explorer: str, environment: str) -> str:
    return f"{explorer}-{environment}-data-import"


def read_import_stack(cloudformation: Any, name: str) -> ImportStack:
    stack = cloudformation.describe_stacks(StackName=name)["Stacks"][0]
    outputs = {
        output["OutputKey"]: output["OutputValue"]
        for output in stack.get("Outputs", [])
    }
    missing = [key for key in REQUIRED_OUTPUTS if not outputs.get(key)]
    if missing:
        raise SystemExit(
            f"Stack {name} is missing the outputs {', '.join(missing)}. "
            "Deploy the environment, then run the import again."
        )
    return ImportStack(
        cluster=outputs["ClusterName"],
        family=outputs["TaskDefinitionFamily"],
        subnet_ids=outputs["SubnetIds"].split(","),
        security_group_id=outputs["SecurityGroupId"],
        log_group=outputs["LogGroupName"],
        container=outputs["ContainerName"],
    )


def running_import_tasks(ecs: Any, stack: ImportStack) -> list[str]:
    return ecs.list_tasks(
        cluster=stack.cluster, family=stack.family, desiredStatus="RUNNING"
    )["taskArns"]


def start_import(ecs: Any, stack: ImportStack, started_by: str) -> str:
    response = ecs.run_task(
        cluster=stack.cluster,
        taskDefinition=stack.family,
        launchType="FARGATE",
        count=1,
        startedBy=started_by[:STARTED_BY_MAX_LENGTH],
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": stack.subnet_ids,
                "securityGroups": [stack.security_group_id],
                "assignPublicIp": "DISABLED",
            }
        },
    )
    if response.get("failures") or not response.get("tasks"):
        reasons = "; ".join(
            f"{failure.get('reason')}: {failure.get('detail', '')}".strip(": ")
            for failure in response.get("failures", [])
        )
        raise SystemExit(
            f"The data import task did not start ({reasons or 'no task returned'}). "
            "The database was not changed."
        )
    return response["tasks"][0]["taskArn"]


def log_stream_name(stack: ImportStack, task_arn: str) -> str:
    task_id = task_arn.rsplit("/", 1)[-1]
    return f"import/{stack.container}/{task_id}"


def format_log_line(message: str) -> str:
    """Show the loader's JSON records as short readable lines"""
    try:
        record = json.loads(message)
    except json.JSONDecodeError:
        return message
    if not isinstance(record, dict):
        return message
    clock = str(record.get("time", ""))[11:19]
    line = f"{clock} {record.get('level', '')} {record.get('event') or '-'}: {record.get('message', '')}"
    if record.get("exception"):
        line += f"\n{record['exception']}"
    return line


class LogFollower:
    """Reads a task's log stream from where the last read stopped"""

    def __init__(self, logs: Any, log_group: str, log_stream: str) -> None:
        self.logs = logs
        self.log_group = log_group
        self.log_stream = log_stream
        self.next_token: str | None = None

    def read_new_lines(self) -> list[str]:
        lines: list[str] = []
        while True:
            request = {
                "logGroupName": self.log_group,
                "logStreamName": self.log_stream,
                "startFromHead": True,
            }
            if self.next_token:
                request["nextToken"] = self.next_token
            try:
                response = self.logs.get_log_events(**request)
            except self.logs.exceptions.ResourceNotFoundException:
                # The stream appears once the container has started.
                return lines
            lines += [event["message"] for event in response["events"]]
            token = response["nextForwardToken"]
            if token == self.next_token:
                return lines
            self.next_token = token


def describe_task(ecs: Any, cluster: str, task_arn: str) -> dict:
    return ecs.describe_tasks(cluster=cluster, tasks=[task_arn])["tasks"][0]


def import_result(task: dict, container: str) -> ImportResult:
    details = next(
        (item for item in task.get("containers", []) if item["name"] == container),
        {},
    )
    return ImportResult(
        exit_code=details.get("exitCode"),
        stopped_reason=task.get("stoppedReason", ""),
        container_reason=details.get("reason"),
    )


def follow_import(
    ecs: Any,
    follower: LogFollower,
    stack: ImportStack,
    task_arn: str,
    sleep: Callable[[float], None] = time.sleep,
    poll_seconds: float = POLL_SECONDS,
) -> ImportResult:
    """Print the task's log until it stops, then return how it ended"""
    while True:
        for line in follower.read_new_lines():
            print(format_log_line(line), flush=True)
        task = describe_task(ecs, stack.cluster, task_arn)
        if task.get("lastStatus") == STOPPED:
            # Lines written just before the stop arrive a few seconds late.
            for line in follower.read_new_lines():
                print(format_log_line(line), flush=True)
            return import_result(task, stack.container)
        sleep(poll_seconds)


def stop_import(ecs: Any, cluster: str, task_arn: str) -> None:
    ecs.stop_task(cluster=cluster, task=task_arn, reason=CANCEL_REASON)


def summary_lines(target: str, task_arn: str, result: ImportResult) -> list[str]:
    outcome = "succeeded" if result.succeeded else "failed"
    lines = [f"- **{target}**: data import {outcome}", f"- Task: `{task_arn}`"]
    if result.exit_code is None:
        lines.append("- The loader never started or was killed, so it has no exit code")
    else:
        lines.append(f"- Loader exit code: {result.exit_code}")
    if result.stopped_reason:
        lines.append(f"- Stopped reason: {result.stopped_reason}")
    if result.container_reason:
        lines.append(f"- Container reason: {result.container_reason}")
    return lines


def write_github_file(variable: str, text: str) -> None:
    path = os.getenv(variable)
    if path:
        with open(path, "a") as github_file:
            github_file.write(text)


def raise_keyboard_interrupt(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--explorer", required=True)
    parser.add_argument("--environment", required=True)
    args = parser.parse_args()
    target = f"{args.explorer}/{args.environment}"

    region = os.getenv("AWS_REGION") or DEFAULT_REGION
    ecs = boto3.client("ecs", region_name=region)
    stack = read_import_stack(
        boto3.client("cloudformation", region_name=region),
        stack_name(args.explorer, args.environment),
    )

    running = running_import_tasks(ecs, stack)
    if running:
        raise SystemExit(
            f"Another data import for {target} is running: {', '.join(running)}. "
            "Wait for it to finish or stop it, then run this again."
        )

    task_arn = start_import(
        ecs, stack, started_by=f"github-{os.getenv('GITHUB_RUN_ID', 'manual')}"
    )
    write_github_file("GITHUB_OUTPUT", f"task_arn={task_arn}\n")
    logger.info("Started %s", task_arn)

    # GitHub cancels a step with SIGINT, then SIGTERM.
    signal.signal(signal.SIGTERM, raise_keyboard_interrupt)
    follower = LogFollower(
        boto3.client("logs", region_name=region),
        stack.log_group,
        log_stream_name(stack, task_arn),
    )
    try:
        result = follow_import(ecs, follower, stack, task_arn)
    except KeyboardInterrupt:
        stop_import(ecs, stack.cluster, task_arn)
        logger.warning("Cancelled: asked ECS to stop %s", task_arn)
        sys.exit(130)

    lines = summary_lines(target, task_arn, result)
    for line in lines:
        logger.info(line)
    write_github_file(
        "GITHUB_STEP_SUMMARY", "### Data import\n\n" + "\n".join(lines) + "\n"
    )
    sys.exit(0 if result.succeeded else 1)


if __name__ == "__main__":
    main()
