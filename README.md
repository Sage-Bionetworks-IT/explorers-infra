# explorers-infra

AWS CDK infrastructure for the Explorer apps, the Sage web apps built in
[sage-monorepo](https://github.com/Sage-Bionetworks/sage-monorepo). This repo deploys each explorer
environment to AWS ECS from its own config file in [config/](./config/). It's for the developers
who release those apps.

Explorers deployed from this repo:

- **xQTL Explorer**: [config/qtl/](./config/qtl/), [dev site](https://dev.xqtlexplorer.adknowledgeportal.org/)

## Quick start

Open the repo in its dev container, create a `.env` file with `GITHUB_TOKEN`, `EXPLORER` and
`ENV`, then synthesize the stacks:

```console
env $(cat .env | xargs) uv run cdk synth
```

See [Development](./docs/development.md) for the token and the rest of the setup.

# Configuration

The `EXPLORER` and `ENV` environment variables tell the CDK which explorer environment to
synthesize or deploy. Its settings come from two files:

- `config/<explorer>/base.yaml`: settings every environment of that explorer shares
- `config/<explorer>/<env>.yaml`: settings for one environment (`dev`, `stage` or `prod`),
  merged over `base.yaml`

[config/qtl/dev.yaml](./config/qtl/dev.yaml) is a complete example, with a comment on every key.

| Key                   | Meaning                                                              |
| --------------------- | -------------------------------------------------------------------- |
| `AWS_ROLE_ARN`        | OIDC role the deploy workflow assumes in the environment's account   |
| `VPC_CIDR`            | CIDR block of the environment's VPC                                  |
| `FQDN`                | Domain the app is served at                                          |
| `CERTIFICATE_ID`      | ID of the ACM certificate for `FQDN`                                 |
| `TAGS`                | Tags applied to every AWS resource: `CostCenter` in `base.yaml`, `Environment` per environment |
| `AUTO_SCALE_CAPACITY` | `MIN` and `MAX` number of tasks per ECS service                      |
| `GTM_CONTAINER_ID`    | Google Tag Manager container ID; empty turns Google Tag Manager off  |
| `APP_VERSION`         | Image tag to deploy: `edge` or a release candidate such as `4.0.0-rc3` |

Missing or unknown keys and wrong types stop the synth with an error naming the file and key.

For example, synthesis with the QTL `prod` settings:

```console
GITHUB_TOKEN=<token> EXPLORER=qtl ENV=prod uv run cdk synth
```

> [!NOTE]
> The `VPC_CIDR` must be a unique value within the Sage AWS organization. See the IT
> [wiki](https://sagebionetworks.jira.com/wiki/spaces/IT/pages/2850586648/Setup+AWS+VPC)
> for information on how to obtain a unique CIDR

## Adding an explorer or environment

1. Add `config/<explorer>/base.yaml` and `config/<explorer>/<env>.yaml`. Before the first
   deploy, the environment needs a unique `VPC_CIDR` (see the note above), an ACM certificate
   for `CERTIFICATE_ID` (see [AWS setup](./docs/aws-setup.md)) and the OIDC role in
   `AWS_ROLE_ARN`, which Sage IT creates in that AWS account.
2. Create the `<explorer>-<env>` GitHub environment, limited to the `main` branch.
3. Add `<explorer>/<env>` to `DEPLOYABLE_TARGETS` in [tools/deploy_plan.py](./tools/deploy_plan.py).
   Until then, neither merges nor manual runs deploy it. The merge that adds it doesn't deploy it
   either, because `tools/` isn't CDK code, so run the deploy workflow once afterwards.

# How deploys work

Every explorer environment deploys from `main` with GitHub Actions:

- A PR to `main` runs the checks: dependency audit, unit tests and `cdk synth`.
- Merging to `main` runs the [deploy workflow](./.github/workflows/deploy.yaml). Its plan step
  deploys each deployable target whose own config (`config/<explorer>/base.yaml` or
  `config/<explorer>/<env>.yaml`) or CDK code (`app.py`, `cdk.json`, `pyproject.toml`, `uv.lock`
  or `src/`) changed, and the run summary says why each target deploys or why nothing does.
- **Actions → deploy → Run workflow** on `main` redeploys every deployable target, e.g. to pick up new
  `edge` images. Anyone with write access to this repo can run it.
- Each target deploys in its own job, with the role in its `AWS_ROLE_ARN`, through the
  `<explorer>-<env>` GitHub environment (e.g. `qtl-dev`). A failed deploy doesn't stop the
  other targets, and isn't retried by the next merge, because the plan compares each merge only
  with the one before it. To retry, run the deploy workflow, which deploys the latest `main`.
  **Re-run failed jobs** deploys that run's commit, so use it only on the latest run.
- The deployable targets are listed in `DEPLOYABLE_TARGETS` in
  [tools/deploy_plan.py](./tools/deploy_plan.py). Today that's `qtl/dev`.

> [!NOTE]
> A deploy flow diagram is coming soon.

See [Releasing](./docs/releasing.md) for the release steps.

# Documentation

- [Development](./docs/development.md): dev container, local development and tests
- [AWS setup](./docs/aws-setup.md): bootstrap, AWS CLI login, certificates, secrets, DNS,
  debugging and manual deploys
- [Releasing](./docs/releasing.md): dev, staging, production and hotfix deployments
