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

# How deploys work

Every explorer environment deploys from `main` with GitHub Actions:

- A PR to `main` runs the checks: dependency audit, unit tests and `cdk synth`.
- Merging to `main` runs the [deploy workflow](./.github/workflows/deploy.yaml). Its plan step
  deploys each deployable target whose `config/<explorer>/*.yaml` or CDK code changed, and the
  run summary says why.
- **Actions → deploy → Run workflow** redeploys every deployable target, e.g. to pick up new
  `edge` images.
- Each target deploys with the role in its `AWS_ROLE_ARN`, through the `<explorer>-<env>`
  GitHub environment (e.g. `qtl-dev`).

Only `qtl/dev` is deployable for now. See [Releasing](./docs/releasing.md) for the release steps.

![CI deployment workflow](docs/ci-deployment-workflow.png)

# Documentation

- [Development](./docs/development.md): dev container, local development and tests
- [AWS setup](./docs/aws-setup.md): bootstrap, AWS CLI login, certificates, secrets, DNS,
  debugging and manual deploys
- [Releasing](./docs/releasing.md): dev, staging, production and hotfix deployments
