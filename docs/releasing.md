# Releasing

How to release an explorer to dev, staging and production, and how to ship a production hotfix.
The examples use the xQTL Explorer (`qtl`); for another explorer, replace `qtl` with its name.

> [!IMPORTANT]
> Only `qtl/dev` is deployable from this repo for now. Merging a change to
> `config/qtl/stage.yaml` or `config/qtl/prod.yaml` records the version but doesn't deploy it
> yet ([EX-169](https://sagebionetworks.jira.com/browse/EX-169)).
<!-- TODO(EX-169): make qtl stage and prod deployable -->

> [!IMPORTANT]
> The data release process is coming soon ([EX-7](https://sagebionetworks.jira.com/browse/EX-7)).

## How releases work

The app code lives in [sage-monorepo](https://github.com/Sage-Bionetworks/sage-monorepo), which
publishes the app, API and apex images to
[GHCR](https://github.com/orgs/Sage-Bionetworks/packages?tab=packages&q=qtl). This repo deploys
those images to AWS Fargate. `APP_VERSION` in `config/<explorer>/<env>.yaml` picks which images
an environment runs:

| Environment | `APP_VERSION`                         | Images come from                        | Deploys when                                                                     |
| ----------- | ------------------------------------- | --------------------------------------- | -------------------------------------------------------------------------------- |
| dev         | `edge`                                | every merge to sage-monorepo `main`     | the [deploy workflow](https://github.com/Sage-Bionetworks-IT/explorers-infra/actions/workflows/deploy.yaml) is run manually, or a merge changes its config or CDK code |
| stage       | a release candidate, e.g. `4.0.0-rc3` | a `qtl/v4.0.0-rc3` tag in sage-monorepo | the config change is merged to `main` in this repo (not yet: [EX-169](https://sagebionetworks.jira.com/browse/EX-169))        |
| prod        | the version staging runs              | the same tag                            | the config change is merged to `main` in this repo (not yet: [EX-169](https://sagebionetworks.jira.com/browse/EX-169))        |

Releases flow dev → stage → prod. A production hotfix branches from the release tag instead; see
[Hotfix deployment](#hotfix-deployment).

The site can take a few minutes to switch to the new version after the deploy workflow finishes.
The rollout is visible in the AWS console under ECS.

## Dev deployment

Dev runs `edge`, the newest images published from sage-monorepo `main`. Its app footer shows the
image's commit SHA.

1. After a PR that affects the explorer merges to `main` in sage-monorepo, wait for the
   [ci workflow](https://github.com/Sage-Bionetworks/sage-monorepo/actions/workflows/ci.yml) to
   publish the new images to GHCR.
2. Run the [deploy workflow](https://github.com/Sage-Bionetworks-IT/explorers-infra/actions/workflows/deploy.yaml): **Actions → deploy → Run workflow** on `main`. Wait for it to finish.
3. Confirm that the [dev site](https://dev.xqtlexplorer.adknowledgeportal.org/) shows the changes
   from the last merged PR.

## Staging deployment

> [!NOTE]
> Until [EX-169](https://sagebionetworks.jira.com/browse/EX-169), stop after merging in step 5: the merge only records the version in
> `config/qtl/stage.yaml`. Waiting for the deploy and step 6 apply once stage is deployable.

1. Pick the next release candidate tag from the
   [sage-monorepo tags](https://github.com/Sage-Bionetworks/sage-monorepo/tags), following
   [semver](https://semver.org/):
   - If the last `qtl` tag is a release candidate, such as `qtl/v4.0.0-rc2`, the next tag is
     `qtl/v4.0.0-rc3`.
   - If the last release is final, such as `qtl/release/v4.0.0`, the next tag is the first release
     candidate of a new version: `qtl/v4.0.1-rc1` for a patch, or `qtl/v4.1.0-rc1` for a minor
     version.
2. Tag sage-monorepo `main` from its dev container:

   ```console
   git checkout main
   git fetch upstream
   git rebase upstream/main
   git tag qtl/v4.0.0-rc3
   git push upstream tag qtl/v4.0.0-rc3
   ```

3. Wait for the sage-monorepo
   [release workflow](https://github.com/Sage-Bionetworks/sage-monorepo/actions/workflows/release.yml)
   to publish the tagged images to GHCR.
4. In this repo, create a branch and set `APP_VERSION` in `config/qtl/stage.yaml` to the version
   without the tag prefix: `4.0.0-rc3`, not `qtl/v4.0.0-rc3`. Open a PR to `main`.
5. Merge the PR and wait for the [deploy workflow](https://github.com/Sage-Bionetworks-IT/explorers-infra/actions/workflows/deploy.yaml) to finish.
6. Confirm that the [staging site](https://stage.xqtlexplorer.adknowledgeportal.org/) shows the new
   version in the app footer.

## Production deployment

> [!NOTE]
> Until [EX-169](https://sagebionetworks.jira.com/browse/EX-169), take the version in step 1 from `config/qtl/stage.yaml` instead of the
> staging site, and stop after merging in step 4: the merge only records the version in
> `config/qtl/prod.yaml`. Waiting for the deploy and step 5 apply once prod is deployable.

1. Note the version in the staging site's app footer, such as `qtl/v4.0.0-rc3`. Its release tag
   is `qtl/release/v4.0.0`.
2. Tag the same commit in sage-monorepo from its dev container:

   ```console
   git checkout main
   git fetch upstream
   git rebase upstream/main
   git rev-list -n 1 qtl/v4.0.0-rc3
   git tag qtl/release/v4.0.0 {commit hash}
   git log --oneline
   ```

   Check in `git log` that the new tag sits on the same commit as the release candidate tag, then
   push it:

   ```console
   git push upstream tag qtl/release/v4.0.0
   ```

3. In this repo, create a branch and set `APP_VERSION` in `config/qtl/prod.yaml` to the version
   staging runs, such as `4.0.0-rc3`. Open a PR to `main`.
4. Merge the PR and wait for the [deploy workflow](https://github.com/Sage-Bionetworks-IT/explorers-infra/actions/workflows/deploy.yaml) to finish.
5. Confirm that the [production site](https://xqtlexplorer.adknowledgeportal.org/) shows the same
   version in the app footer as the staging site.

## Hotfix Deployment

When a critical bug is discovered in production, use this workflow to deploy a fix quickly while maintaining proper version control and ensuring the fix is not lost in future releases. This process uses a fork-based maintainer workflow with short-lived release branches.

### sage-monorepo: Create Hotfix Branch and Apply Fix

1. **Create the release branch in upstream sage-monorepo**

   As a maintainer, isolate the baseline code by creating a hotfix branch directly from the affected version's release tag (e.g., `qtl/release/v1.0.0`).

   ```console
   git fetch upstream --tags
   git checkout -b qtl/hotfix/v1.0.1 qtl/release/v1.0.0
   git push upstream qtl/hotfix/v1.0.1
   ```

2. **Branch from your fork**

   In your local environment (connected to your origin fork), fetch the new upstream branch and create your working feature branch.

   ```console
   git fetch upstream
   git checkout -b hotfix/{jira-ticket} upstream/qtl/hotfix/v1.0.1
   ```

3. **Commit the fix and push to fork**

   Apply the fix, run local tests, commit the changes, and push the branch to your fork.

   ```console
   git add .
   git commit -m "fix(qtl): resolve production issue ({jira-ticket})"
   git push origin hotfix/{jira-ticket}
   ```

4. **Submit Pull Request to the release branch**

   Open a Pull Request on GitHub:
   - Source: `your-fork/hotfix/{jira-ticket}`
   - Target: `upstream/qtl/hotfix/v1.0.1`

5. **Merge and tag the release**

   Once the PR passes CI and code review, merge it into `upstream/qtl/hotfix/v1.0.1`. Then create and push the release candidate tag.

   ```console
   git checkout qtl/hotfix/v1.0.1
   git pull upstream qtl/hotfix/v1.0.1
   git tag qtl/v1.0.1-rc1
   git push upstream qtl/v1.0.1-rc1
   ```

   Wait for sage-monorepo [release GHA job](https://github.com/Sage-Bionetworks/sage-monorepo/actions/workflows/release.yml) to successfully build, tag, and push images to GHCR.

   > [!NOTE]
   > If multiple fixes are needed for the same hotfix release, additional PRs can be made to the same `qtl/hotfix/v1.0.1` branch. Increment the release candidate number for each subsequent fix (e.g., `v1.0.1-rc1`, `v1.0.1-rc2`, etc.).

### explorers-infra repo: Deploy to Staging

6. **Point staging at the hotfix tag**

   Create a new branch from `main` in this repo:

   ```console
   git checkout main
   git pull upstream main
   git checkout -b hotfix/update-to-v1.0.1-rc1
   ```

   Set `APP_VERSION` in `config/qtl/stage.yaml` to the new hotfix version (e.g., `1.0.1-rc1`), then:

   ```console
   git add config/qtl/stage.yaml
   git commit -m "chore: update stage to hotfix v1.0.1-rc1"
   git push origin hotfix/update-to-v1.0.1-rc1
   ```

   Create PR **to `main`**.

7. **Deploy to staging**

   Merge PR. Wait for the [deploy workflow](https://github.com/Sage-Bionetworks-IT/explorers-infra/actions/workflows/deploy.yaml) to successfully update staging deployment. Deployment can be monitored in AWS console in AWS ECS.

   Confirm that [staging site](https://stage.xqtlexplorer.adknowledgeportal.org/) shows the hotfix version tag in the app footer.

### sage-monorepo: Create Production Release Tag

8. **Tag the production release**

   Create the final production release tag pointing to the same commit as the release candidate tag.

   ```console
   git checkout qtl/hotfix/v1.0.1
   git pull upstream qtl/hotfix/v1.0.1
   git rev-list -n 1 qtl/v1.0.1-rc1
   git tag qtl/release/v1.0.1 {commit hash}
   ```

   Confirm that the new tag is on the same commit as the previous tag by reviewing the git log:

   ```console
   git log --oneline
   ```

   Push the tag:

   ```console
   git push upstream qtl/release/v1.0.1
   ```

### explorers-infra repo: Deploy to Production

9. **Deploy to production**

    Create a new branch from `main`, set `APP_VERSION` in `config/qtl/prod.yaml` to the hotfix version staging runs (e.g., `1.0.1-rc1`), and create a PR **to `main`**.

    Merge PR. Wait for the [deploy workflow](https://github.com/Sage-Bionetworks-IT/explorers-infra/actions/workflows/deploy.yaml) to successfully update prod deployment. Deployment can be monitored in AWS console in AWS ECS.

    Confirm that [production site](https://xqtlexplorer.adknowledgeportal.org/) shows the hotfix version tag in the app footer.

### sage-monorepo: Backport to Main

10. **Submit Pull Request in sage-monorepo to backport the fix**

    To ensure the fix is not lost in future releases, submit a backport Pull Request:
    - Source: `upstream/qtl/hotfix/v1.0.1`
    - Target: `upstream/main`

    > [!NOTE]
    > Resolve any merge conflicts that occurred due to changes on main since the original release.
