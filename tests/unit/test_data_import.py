import json

import boto3
import pytest
from botocore.stub import Stubber

from tools.data_import import (
    CANCEL_REASON,
    ImportResult,
    ImportStack,
    LogFollower,
    follow_import,
    format_log_line,
    import_result,
    log_stream_name,
    read_import_stack,
    running_import_tasks,
    start_import,
    stop_import,
    summary_lines,
)

REGION = "us-east-1"
TASK_ARN = "arn:aws:ecs:us-east-1:123456789012:task/example-cluster/abc123"
STACK = ImportStack(
    cluster="example-cluster",
    family="example-dev-data-import",
    subnet_ids=["subnet-1", "subnet-2"],
    security_group_id="sg-1",
    log_group="/example/dev/data-import",
    container="example-data",
)
OUTPUTS = {
    "ClusterName": STACK.cluster,
    "TaskDefinitionFamily": STACK.family,
    "SubnetIds": "subnet-1,subnet-2",
    "SecurityGroupId": STACK.security_group_id,
    "LogGroupName": STACK.log_group,
    "ContainerName": STACK.container,
}
STREAM = "import/example-data/abc123"


def client(service: str):
    return boto3.client(
        service,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture
def ecs():
    ecs = client("ecs")
    with Stubber(ecs) as stubber:
        yield ecs, stubber
        stubber.assert_no_pending_responses()


@pytest.fixture
def logs():
    logs = client("logs")
    with Stubber(logs) as stubber:
        yield logs, stubber
        stubber.assert_no_pending_responses()


def stopped_task(exit_code: int | None, stopped_reason: str = "") -> dict:
    container = {"name": STACK.container}
    if exit_code is not None:
        container["exitCode"] = exit_code
    return {
        "taskArn": TASK_ARN,
        "lastStatus": "STOPPED",
        "stoppedReason": stopped_reason,
        "containers": [container],
    }


def test_reads_the_stack_outputs():
    cloudformation = client("cloudformation")
    with Stubber(cloudformation) as stubber:
        stubber.add_response(
            "describe_stacks",
            {
                "Stacks": [
                    {
                        "StackName": "example-dev-data-import",
                        "CreationTime": "2026-11-24T00:00:00Z",
                        "StackStatus": "CREATE_COMPLETE",
                        "Outputs": [
                            {"OutputKey": key, "OutputValue": value}
                            for key, value in OUTPUTS.items()
                        ],
                    }
                ]
            },
            {"StackName": "example-dev-data-import"},
        )
        assert read_import_stack(cloudformation, "example-dev-data-import") == STACK


def test_missing_outputs_stop_with_a_message():
    cloudformation = client("cloudformation")
    with Stubber(cloudformation) as stubber:
        stubber.add_response(
            "describe_stacks",
            {
                "Stacks": [
                    {
                        "StackName": "example-dev-data-import",
                        "CreationTime": "2026-11-24T00:00:00Z",
                        "StackStatus": "CREATE_COMPLETE",
                    }
                ]
            },
        )
        with pytest.raises(SystemExit, match="missing the outputs ClusterName"):
            read_import_stack(cloudformation, "example-dev-data-import")


def test_lists_running_imports_of_the_family(ecs):
    ecs, stubber = ecs
    stubber.add_response(
        "list_tasks",
        {"taskArns": [TASK_ARN]},
        {
            "cluster": STACK.cluster,
            "family": STACK.family,
            "desiredStatus": "RUNNING",
        },
    )
    assert running_import_tasks(ecs, STACK) == [TASK_ARN]


def test_starts_the_task_in_the_private_subnets(ecs):
    ecs, stubber = ecs
    stubber.add_response(
        "run_task",
        {"tasks": [{"taskArn": TASK_ARN}], "failures": []},
        {
            "cluster": STACK.cluster,
            "taskDefinition": STACK.family,
            "launchType": "FARGATE",
            "count": 1,
            "startedBy": "github-123",
            "networkConfiguration": {
                "awsvpcConfiguration": {
                    "subnets": STACK.subnet_ids,
                    "securityGroups": [STACK.security_group_id],
                    "assignPublicIp": "DISABLED",
                }
            },
        },
    )
    assert start_import(ecs, STACK, started_by="github-123") == TASK_ARN


def test_a_task_that_aws_refuses_stops_with_its_reason(ecs):
    ecs, stubber = ecs
    stubber.add_response(
        "run_task",
        {"tasks": [], "failures": [{"reason": "RESOURCE:MEMORY"}]},
    )
    with pytest.raises(SystemExit, match="RESOURCE:MEMORY"):
        start_import(ecs, STACK, started_by="github-123")


def test_log_stream_follows_the_task_id():
    assert log_stream_name(STACK, TASK_ARN) == STREAM


def test_loader_records_become_short_lines():
    record = {
        "time": "2026-11-24T05:06:07.890+00:00",
        "level": "INFO",
        "event": "collection_imported",
        "message": "Imported eqtl_results",
    }
    assert (
        format_log_line(json.dumps(record))
        == "05:06:07 INFO collection_imported: Imported eqtl_results"
    )
    assert format_log_line("plain text") == "plain text"


def test_follower_reads_each_line_once(logs):
    logs, stubber = logs
    stubber.add_client_error("get_log_events", "ResourceNotFoundException")
    stubber.add_response(
        "get_log_events",
        {"events": [{"message": "one"}, {"message": "two"}], "nextForwardToken": "t1"},
    )
    stubber.add_response("get_log_events", {"events": [], "nextForwardToken": "t1"})
    stubber.add_response(
        "get_log_events",
        {"events": [{"message": "three"}], "nextForwardToken": "t2"},
        {
            "logGroupName": STACK.log_group,
            "logStreamName": STREAM,
            "startFromHead": True,
            "nextToken": "t1",
        },
    )
    stubber.add_response("get_log_events", {"events": [], "nextForwardToken": "t2"})
    follower = LogFollower(logs, STACK.log_group, STREAM)
    assert follower.read_new_lines() == []
    assert follower.read_new_lines() == ["one", "two"]
    assert follower.read_new_lines() == ["three"]


def test_follow_waits_until_the_task_stops(ecs, logs, capsys):
    ecs, ecs_stubber = ecs
    logs, logs_stubber = logs
    running = {"taskArn": TASK_ARN, "lastStatus": "RUNNING", "containers": []}
    logs_stubber.add_response(
        "get_log_events", {"events": [{"message": "loading"}], "nextForwardToken": "a"}
    )
    logs_stubber.add_response("get_log_events", {"events": [], "nextForwardToken": "a"})
    ecs_stubber.add_response("describe_tasks", {"tasks": [running]})
    logs_stubber.add_response("get_log_events", {"events": [], "nextForwardToken": "a"})
    ecs_stubber.add_response("describe_tasks", {"tasks": [stopped_task(0)]})
    logs_stubber.add_response(
        "get_log_events", {"events": [{"message": "done"}], "nextForwardToken": "b"}
    )
    logs_stubber.add_response("get_log_events", {"events": [], "nextForwardToken": "b"})
    sleeps = []

    result = follow_import(
        ecs, LogFollower(logs, STACK.log_group, STREAM), STACK, TASK_ARN, sleeps.append
    )

    assert result.succeeded
    assert sleeps == [15]
    assert capsys.readouterr().out.splitlines() == ["loading", "done"]


@pytest.mark.parametrize(
    ("task", "exit_code", "succeeded"),
    [
        (stopped_task(0), 0, True),
        (stopped_task(1, "Essential container in task exited"), 1, False),
        (stopped_task(None, "CannotPullContainerError: not found"), None, False),
    ],
)
def test_result_comes_from_the_loader_exit_code(task, exit_code, succeeded):
    result = import_result(task, STACK.container)
    assert result.exit_code == exit_code
    assert result.succeeded is succeeded


def test_summary_explains_a_task_that_never_ran():
    result = ImportResult(
        exit_code=None,
        stopped_reason="CannotPullContainerError: not found",
        container_reason=None,
    )
    lines = summary_lines("example/dev", TASK_ARN, result)
    assert lines[0] == "- **example/dev**: data import failed"
    assert "never started or was killed" in lines[2]
    assert "CannotPullContainerError" in lines[3]


def test_cancel_stops_the_task(ecs):
    ecs, stubber = ecs
    stubber.add_response(
        "stop_task",
        {},
        {"cluster": STACK.cluster, "task": TASK_ARN, "reason": CANCEL_REASON},
    )
    stop_import(ecs, STACK.cluster, TASK_ARN)


def stub_clients(monkeypatch, ecs, logs):
    cloudformation = client("cloudformation")
    stubber = Stubber(cloudformation)
    stubber.add_response(
        "describe_stacks",
        {
            "Stacks": [
                {
                    "StackName": "example-dev-data-import",
                    "CreationTime": "2026-11-24T00:00:00Z",
                    "StackStatus": "CREATE_COMPLETE",
                    "Outputs": [
                        {"OutputKey": key, "OutputValue": value}
                        for key, value in OUTPUTS.items()
                    ],
                }
            ]
        },
    )
    stubber.activate()
    clients = {"ecs": ecs, "logs": logs, "cloudformation": cloudformation}
    monkeypatch.setattr(
        "tools.data_import.boto3.client", lambda service, **_: clients[service]
    )
    monkeypatch.setattr(
        "sys.argv",
        ["data_import", "--explorer", "example", "--environment", "dev"],
    )


def test_main_refuses_while_another_import_runs(monkeypatch, ecs, logs):
    from tools.data_import import main

    ecs, stubber = ecs
    stub_clients(monkeypatch, ecs, logs[0])
    stubber.add_response("list_tasks", {"taskArns": [TASK_ARN]})
    with pytest.raises(SystemExit, match="Another data import for example/dev"):
        main()


def test_main_stops_the_task_when_the_run_is_cancelled(
    monkeypatch, ecs, logs, tmp_path
):
    from tools.data_import import main

    ecs, stubber = ecs
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    stub_clients(monkeypatch, ecs, logs[0])
    stubber.add_response("list_tasks", {"taskArns": []})
    stubber.add_response("run_task", {"tasks": [{"taskArn": TASK_ARN}], "failures": []})
    stubber.add_response(
        "stop_task",
        {},
        {"cluster": STACK.cluster, "task": TASK_ARN, "reason": CANCEL_REASON},
    )

    def cancelled(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("tools.data_import.follow_import", cancelled)
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 130
    assert output.read_text() == f"task_arn={TASK_ARN}\n"
