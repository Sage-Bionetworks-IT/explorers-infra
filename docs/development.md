# Development

# Dev Container

This repository provides a [dev container](https://containers.dev/) that includes all the tools
required to develop this AWS CDK app.

## Opening the project inside its dev container

With VS Code:

1. Clone this repo
2. File > Open Folder...
3. A prompt should invite you to open the project inside the dev container. If not, open VS Code
   Command Palette and select "Dev Containers: Open Folder in Container..."

With GitHub Codespaces:

1. From the main page of this repository, click on the button "Code" > Codespaces > Click on the
   button "Create codespace"

That's it! You are now inside the dev container and have access to all the development tools.

# Local development

All the development tools are provided when developing inside the dev container
(see above). These tools include Python, AWS CLI, AWS CDK CLI, etc. These tools
also include a Python virtual environment where all the Python packages needed
are already installed.

If you decide to develop outside of the dev container, you'll need
[uv](https://docs.astral.sh/uv/getting-started/installation/) installed.
Then run:

```console
./tools/setup.sh
```

This creates a `.venv` and installs Python dependencies from `uv.lock`.
Run Python commands via `uv run` so they execute inside the managed env:

```console
$ uv run cdk synth
```

(You can also `source .venv/bin/activate` once and drop the `uv run` prefix
for the rest of your shell session.)

To add or remove dependencies, use `uv add <pkg>` / `uv add --group dev <pkg>` /
`uv remove <pkg>`. These commands update both `pyproject.toml` and `uv.lock`
automatically. The `uv-lock` pre-commit hook also keeps the lockfile in sync
when `pyproject.toml` changes.

## Useful commands

- `cdk ls` list all stacks in the app
- `cdk synth` emits the synthesized CloudFormation template
- `cdk deploy` deploy this stack to your default AWS account/region
- `cdk diff` compare deployed stack with current state
- `cdk docs` open CDK documentation

# Testing

## Static Analysis

As a pre-deployment step we syntactically validate the CDK json, yaml and
python files with [pre-commit](https://pre-commit.com).

Please install pre-commit, once installed the file validations will
automatically run on every commit. Alternatively you can manually
execute the validations by running `pre-commit run --all-files`.

Create a [GitHub classic personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-personal-access-token-classic) with `read:packages` access. The token is used to authenticate with the GitHub API and access the packages endpoint to look up the latest image version for each service. Create an `.env` file with the following variables:

```
GITHUB_TOKEN="your-token-here"
EXPLORER="qtl"
ENV="dev"
```

Verify CDK to Cloudformation conversion by running [cdk synth]:

```console
env $(cat .env | xargs) uv run cdk synth
```

The Cloudformation output is saved to the `cdk.out` folder

## Unit Tests

Tests are available in the tests folder. Execute the following to run tests:

```
uv run pytest tests/ -s -v
```
