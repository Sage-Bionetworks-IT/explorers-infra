"""One-off Fargate task that loads a data release into the explorer's DocumentDB."""

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as sm
from constructs import Construct

TASK_CPU = 1024
TASK_MEMORY_MIB = 4096
LOG_RETENTION = logs.RetentionDays.ONE_YEAR
LOG_STREAM_PREFIX = "import"


def synapse_token_secret_name(explorer: str, environment: str) -> str:
    """The Secrets Manager secret, created by hand, that holds the Synapse token"""
    return f"{explorer}-{environment}-synapse-auth-token"


class DataImportStack(cdk.Stack):
    """Task definition, secrets, logs and network access for the data import."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        explorer: str,
        environment: str,
        image_version: str,
        vpc: ec2.IVpc,
        cluster: ecs.ICluster,
        db_host: str,
        db_port: int,
        db_user: str,
        db_password_secret: sm.ISecret,
        db_security_group: ec2.ISecurityGroup,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        name = f"{explorer}-{environment}-data-import"

        self.security_group = ec2.SecurityGroup(
            self,
            "SecurityGroup",
            vpc=vpc,
            security_group_name=name,
            description="Data import task: outbound to Synapse, GHCR and DocumentDB",
            allow_all_outbound=True,
        )
        # Lives here, not in the DocumentDB stack, so the two stacks don't
        # depend on each other.
        ec2.CfnSecurityGroupIngress(
            self,
            "DocumentDbIngress",
            group_id=db_security_group.security_group_id,
            source_security_group_id=self.security_group.security_group_id,
            ip_protocol="tcp",
            from_port=db_port,
            to_port=db_port,
            description=f"Allow the {name} task",
        )

        synapse_token_secret = sm.Secret.from_secret_name_v2(
            self,
            "SynapseAuthToken",
            synapse_token_secret_name(explorer, environment),
        )

        log_group = logs.LogGroup(
            self,
            "LogGroup",
            log_group_name=f"/{explorer}/{environment}/data-import",
            retention=LOG_RETENTION,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        task_definition = ecs.FargateTaskDefinition(
            self,
            "TaskDefinition",
            family=name,
            cpu=TASK_CPU,
            memory_limit_mib=TASK_MEMORY_MIB,
        )
        task_definition.add_container(
            f"{explorer}-data",
            container_name=f"{explorer}-data",
            image=ecs.ContainerImage.from_registry(
                f"ghcr.io/sage-bionetworks/{explorer}-data:{image_version}"
            ),
            # An init process as PID 1, so a stopped task ends the loader at once
            # instead of only after the stop timeout
            linux_parameters=ecs.LinuxParameters(
                self, "LinuxParameters", init_process_enabled=True
            ),
            environment={
                "DB_HOST": db_host,
                "DB_PORT": str(db_port),
                "DB_NAME": explorer,
                "DB_USER": db_user,
                "LOG_FORMAT": "json",
            },
            secrets={
                "DB_PASS": ecs.Secret.from_secrets_manager(db_password_secret),
                "SYNAPSE_AUTH_TOKEN": ecs.Secret.from_secrets_manager(
                    synapse_token_secret
                ),
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix=LOG_STREAM_PREFIX, log_group=log_group
            ),
        )

        outputs = {
            "ClusterName": cluster.cluster_name,
            "TaskDefinitionFamily": name,
            "SubnetIds": ",".join(
                vpc.select_subnets(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ).subnet_ids
            ),
            "SecurityGroupId": self.security_group.security_group_id,
            "LogGroupName": log_group.log_group_name,
            "ContainerName": f"{explorer}-data",
        }
        for output_id, value in outputs.items():
            cdk.CfnOutput(self, output_id, value=value)
