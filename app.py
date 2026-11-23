from os import environ

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2

from src.ecs_stack import EcsStack
from src.helpers.github_helpers import get_image_version, get_short_commit_sha
from src.load_balancer_stack import LoadBalancerStack
from src.network_stack import NetworkStack
from src.service_props import ServiceProps, ServiceSecret
from src.service_stack import LoadBalancedServiceStack, ServiceStack
from src.docdb_props import DocdbProps
from src.docdb_stack import DocdbStack
from src.explorer_config import ConfigError, load_config

try:
    config = load_config(environ.get("EXPLORER"), environ.get("ENV"))
except ConfigError as error:
    raise SystemExit(str(error))

explorer = config.explorer
environment = config.environment
app_name = f"{explorer}-app"
api_name = f"{explorer}-api"
apex_name = f"{explorer}-apex"

TAG_PREFIX = f"{explorer}/v"
stack_name_prefix = f"{explorer}-{environment}"
fully_qualified_domain_name = config.fqdn
environment_tags = config.tags
ghcr_package_version = config.app.version
docdb_master_username = "master"
mongodb_port = 27017
vpn_cidr = "10.1.0.0/16"

# Resolve image tags for each service
app_version = get_image_version(app_name, ghcr_package_version)
api_version = get_image_version(api_name, ghcr_package_version)
apex_version = get_image_version(apex_name, ghcr_package_version)

short_commit_sha = get_short_commit_sha(
    "sage-monorepo", app_version, ghcr_package_version, tag_prefix=TAG_PREFIX
)

print(
    f"Using images: {app_name}:{app_version}, {api_name}:{api_version}, "
    f"{apex_name}:{apex_version}"
)

# Define stacks
cdk_app = cdk.App()

# recursively apply tags to all stack resources
if environment_tags:
    for key, value in environment_tags.items():
        cdk.Tags.of(cdk_app).add(key, value)

network_stack = NetworkStack(
    scope=cdk_app,
    construct_id=f"{stack_name_prefix}-network",
    vpc_cidr=config.vpc_cidr,
)

docdb_props = DocdbProps(
    instance_type=ec2.InstanceType.of(
        ec2.InstanceClass.MEMORY5, ec2.InstanceSize.LARGE
    ),
    master_username=docdb_master_username,
    port=mongodb_port,
    family="docdb8.0",
    engine_version="8.0.0",
)
docdb_stack = DocdbStack(
    scope=cdk_app,
    construct_id=f"{stack_name_prefix}-docdb-v8",
    vpc=network_stack.vpc,
    props=docdb_props,
)
docdb_stack.cluster.connections.allow_from(
    ec2.Peer.ipv4(vpn_cidr), ec2.Port.all_traffic(), "Allow all VPN traffic"
)
# TODO(EX-7): allow the data import job to reach DocumentDB once its approach is decided

ecs_stack = EcsStack(
    scope=cdk_app,
    construct_id=f"{stack_name_prefix}-ecs",
    vpc=network_stack.vpc,
    namespace=fully_qualified_domain_name,
)

# From AWS docs https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-connect-concepts-deploy.html
# The public discovery and reachability should be created last by AWS CloudFormation, including the frontend
# client service. The services need to be created in this order to prevent an time period when the frontend
# client service is running and available the public, but a backend isn't.
load_balancer_stack = LoadBalancerStack(
    scope=cdk_app,
    construct_id=f"{stack_name_prefix}-load-balancer",
    vpc=network_stack.vpc,
)

api_props = ServiceProps(
    container_name=api_name,
    container_location=f"ghcr.io/sage-bionetworks/{api_name}:{api_version}",
    container_port=3333,
    container_memory_reservation=2048,
    container_env_vars={
        "SERVER_PORT": "3333",
        "SPRING_DATA_MONGODB_HOST": docdb_stack.cluster.cluster_endpoint.hostname,
        "SPRING_DATA_MONGODB_PORT": f"{mongodb_port}",
        "SPRING_DATA_MONGODB_DATABASE": explorer,
        "SPRING_DATA_MONGODB_USERNAME": docdb_master_username,
        "SPRING_DATA_MONGODB_AUTHENTICATION_DATABASE": "admin",
        "SPRING_PROFILES_ACTIVE": f"{environment}",
    },
    container_secrets=[
        ServiceSecret(
            secret_name=docdb_stack.master_password_secret.secret_name,
            environment_key="SPRING_DATA_MONGODB_PASSWORD",
        )
    ],
    auto_scale_min_capacity=config.autoscale.min,
    auto_scale_max_capacity=config.autoscale.max,
)
api_stack = ServiceStack(
    scope=cdk_app,
    construct_id=f"{stack_name_prefix}-api",
    vpc=network_stack.vpc,
    cluster=ecs_stack.cluster,
    props=api_props,
)
api_stack.add_dependency(docdb_stack)
api_stack.service.connections.allow_to_default_port(
    docdb_stack.cluster,
    "Allow API container to connect to DocumentDB cluster",
)

app_props = ServiceProps(
    container_name=app_name,
    container_location=f"ghcr.io/sage-bionetworks/{app_name}:{app_version}",
    container_port=4200,
    container_memory_reservation=1024,
    container_env_vars={
        "APP_VERSION": app_version,
        "COMMIT_SHA": short_commit_sha,
        "CSR_API_URL": f"https://{fully_qualified_domain_name}/api/v1",
        "SSR_API_URL": f"http://{api_name}:3333/v1",
        "ENVIRONMENT": environment,
        "GOOGLE_TAG_MANAGER_ENABLED": str(config.google_tag_manager.enabled).lower(),
        "GOOGLE_TAG_MANAGER_ID": config.google_tag_manager.container_id,
        "SENTRY_ENVIRONMENT": environment,
        "SENTRY_RELEASE": f"{explorer}@{ghcr_package_version}+{short_commit_sha}",
    },
    # TODO(EX-161): add the qtl-sentry-dsn secret as SENTRY_DSN once it exists in Secrets Manager
    auto_scale_min_capacity=config.autoscale.min,
    auto_scale_max_capacity=config.autoscale.max,
)
app_stack = ServiceStack(
    scope=cdk_app,
    construct_id=f"{stack_name_prefix}-app",
    vpc=network_stack.vpc,
    cluster=ecs_stack.cluster,
    props=app_props,
)
app_stack.add_dependency(api_stack)

apex_props = ServiceProps(
    container_name=apex_name,
    container_location=f"ghcr.io/sage-bionetworks/{apex_name}:{apex_version}",
    container_port=80,
    container_memory_reservation=200,
    container_env_vars={
        "API_HOST": api_name,
        "API_PORT": "3333",
        "APP_HOST": app_name,
        "APP_PORT": "4200",
    },
    auto_scale_min_capacity=config.autoscale.min,
    auto_scale_max_capacity=config.autoscale.max,
)
apex_stack = LoadBalancedServiceStack(
    scope=cdk_app,
    construct_id=f"{stack_name_prefix}-apex",
    vpc=network_stack.vpc,
    cluster=ecs_stack.cluster,
    props=apex_props,
    load_balancer=load_balancer_stack.alb,
    certificate_id=config.certificate_id,
    health_check_path="/health",
)
apex_stack.add_dependency(app_stack)
apex_stack.add_dependency(api_stack)

cdk_app.synth()
