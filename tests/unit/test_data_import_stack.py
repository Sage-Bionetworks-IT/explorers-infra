import aws_cdk as cdk
import aws_cdk.assertions as assertions
import pytest
from aws_cdk import aws_ec2 as ec2

from src.data_import_stack import (
    LOG_STREAM_PREFIX,
    STOP_TIMEOUT,
    TASK_CPU,
    TASK_MEMORY_MIB,
    DataImportStack,
)
from src.docdb_props import DocdbProps
from src.docdb_stack import DocdbStack
from src.ecs_stack import EcsStack
from src.network_stack import NetworkStack

DB_PORT = 27017


@pytest.fixture(scope="module")
def template() -> assertions.Template:
    app = cdk.App()
    network = NetworkStack(app, "Network", vpc_cidr="10.254.192.0/24")
    docdb = DocdbStack(
        app,
        "Docdb",
        vpc=network.vpc,
        props=DocdbProps(
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.MEMORY5, ec2.InstanceSize.LARGE
            ),
            master_username="master",
            port=DB_PORT,
            family="docdb8.0",
            engine_version="8.0.0",
        ),
    )
    ecs_stack = EcsStack(app, "Ecs", vpc=network.vpc, namespace="dev.example.org")
    stack = DataImportStack(
        app,
        "DataImport",
        explorer="example",
        environment="dev",
        image_version="edge",
        vpc=network.vpc,
        cluster=ecs_stack.cluster,
        db_host=docdb.cluster.cluster_endpoint.hostname,
        db_port=DB_PORT,
        db_user="master",
        db_password_secret=docdb.master_password_secret,
        db_security_group=docdb.cluster.connections.security_groups[0],
    )
    return assertions.Template.from_stack(stack)


def test_task_runs_the_explorer_data_image(template):
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "Family": "example-dev-data-import",
            "Cpu": str(TASK_CPU),
            "Memory": str(TASK_MEMORY_MIB),
            "ContainerDefinitions": [
                assertions.Match.object_like(
                    {
                        "Name": "example-data",
                        "Image": "ghcr.io/sage-bionetworks/example-data:edge",
                        "StopTimeout": STOP_TIMEOUT.to_seconds(),
                        "LinuxParameters": {
                            "Capabilities": {},
                            "InitProcessEnabled": True,
                        },
                    }
                )
            ],
        },
    )


def test_task_gets_the_loader_settings_and_secrets(template):
    container = template.find_resources("AWS::ECS::TaskDefinition")
    definition = next(iter(container.values()))["Properties"][
        "ContainerDefinitions"
    ][0]
    environment = {item["Name"]: item["Value"] for item in definition["Environment"]}
    assert environment["DB_PORT"] == str(DB_PORT)
    assert environment["DB_NAME"] == "example"
    assert environment["DB_USER"] == "master"
    assert environment["LOG_FORMAT"] == "json"
    assert "DB_HOST" in environment
    assert {secret["Name"] for secret in definition["Secrets"]} == {
        "DB_PASS",
        "SYNAPSE_AUTH_TOKEN",
    }
    assert definition["LogConfiguration"]["Options"]["awslogs-stream-prefix"] == (
        LOG_STREAM_PREFIX
    )


def test_documentdb_accepts_the_import_task_on_its_port(template):
    template.has_resource_properties(
        "AWS::EC2::SecurityGroupIngress",
        {
            "IpProtocol": "tcp",
            "FromPort": DB_PORT,
            "ToPort": DB_PORT,
            "SourceSecurityGroupId": assertions.Match.any_value(),
        },
    )


def test_logs_are_kept_for_a_year_and_outlive_the_stack(template):
    template.has_resource(
        "AWS::Logs::LogGroup",
        {
            "Properties": {
                "LogGroupName": "/example/dev/data-import",
                "RetentionInDays": 365,
            },
            "DeletionPolicy": "Retain",
        },
    )


def test_synapse_token_secret_is_named_for_the_environment(template):
    template.has_resource_properties(
        "AWS::SecretsManager::Secret",
        {"Name": "example-dev-synapse-auth-token"},
    )


@pytest.mark.parametrize(
    "output",
    [
        "ClusterName",
        "TaskDefinitionFamily",
        "SubnetIds",
        "SecurityGroupId",
        "LogGroupName",
        "ContainerName",
    ],
)
def test_outputs_what_the_import_run_needs(template, output):
    template.has_output(output, {})
