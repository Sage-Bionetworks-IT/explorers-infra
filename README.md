# explorers-infra

AWS CDK infrastructure for the Explorer apps. Each explorer environment is deployed to ECS from its own config file in [config/](./config/).

Explorers deployed from this repo:

- **xQTL Explorer**: [config/qtl/](./config/qtl/)

# Configuration

The `EXPLORER` and `ENV` environment variables tell the CDK which explorer environment to
synthesize or deploy. Its settings come from two files:

- `config/<explorer>/base.yaml`: settings every environment of that explorer shares
- `config/<explorer>/<env>.yaml`: settings for one environment (`dev`, `stage` or `prod`),
  merged over `base.yaml`

| Key                   | Meaning                                                              |
| --------------------- | -------------------------------------------------------------------- |
| `AWS_ROLE_ARN`        | OIDC role the deploy workflow assumes in the environment's account   |
| `VPC_CIDR`            | CIDR block of the environment's VPC                                  |
| `FQDN`                | Domain the app is served at                                          |
| `CERTIFICATE_ID`      | ID of the ACM certificate for `FQDN`                                 |
| `TAGS`                | Tags applied to every AWS resource                                   |
| `AUTO_SCALE_CAPACITY` | `MIN` and `MAX` number of tasks per ECS service                      |
| `GTM_CONTAINER_ID`    | Google Tag Manager container ID; empty turns Google Tag Manager off  |
| `APP_VERSION`         | Image tag to deploy: `edge` or a release version such as `1.2.0`     |

Missing or unknown keys and wrong types stop the synth with an error naming the file and key.

For example, synthesis with the QTL `prod` settings:

```console
EXPLORER=qtl ENV=prod cdk synth
```

> [!NOTE]
> The `VPC_CIDR` must be a unique value within our AWS organization. Check our
> [wiki](https://sagebionetworks.jira.com/wiki/spaces/IT/pages/2850586648/Setup+AWS+VPC)
> for information on how to obtain a unique CIDR

# CI Workflow

This repo has been set up to use Github Actions CI to continuously deploy the application.

The workflow for continuous integration:

- Create PR from the git dev branch
- PR is reviewed and approved
- PR is merged
- CI deploys changes to the dev environment (dev.app.io) in the AWS dev account.
- Changes are promoted (or merged) to the git stage branch.
- CI deploys changes to the staging environment (stage.app.io) in the AWS prod account.
- Changes are promoted (or merged) to the git prod branch.
- CI deploys changes to the prod environment (prod.app.io) in the AWS prod account.

![CI deployment workflow](docs/ci-deployment-workflow.png)

# Documentation

- [Development](./docs/development.md): dev container, local development and tests
- [AWS setup](./docs/aws-setup.md): bootstrap, AWS CLI login, certificates, secrets, DNS,
  debugging and manual deploys
- [Releasing](./docs/releasing.md): dev, staging, production and hotfix deployments
