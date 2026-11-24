# Releasing

# Deployment Process

## Overview

The source code for the application lives in the [sage-monorepo](https://github.com/Sage-Bionetworks/sage-monorepo). When a new git tag is added in the monorepo, images are published to [GHCR](https://github.com/orgs/Sage-Bionetworks/packages?tab=packages&q=qtl). These images are deployed with GHA to AWS Fargate using infrastructure code in this repo.

For regular deployments, changes flow through dev → stage → prod environments. For production hotfixes, we use a short-lived release branch strategy: create a hotfix branch from the affected release tag in sage-monorepo, apply the fix, deploy to stage/prod, then backport to main.

> [!NOTE]
> There may be a delay before the website updates after any deployment jobs since there is a non-trivial cutover delay (a few minutes).

> [!IMPORTANT]
> The data release process is coming soon ([EX-7](https://sagebionetworks.jira.com/browse/EX-7)).

### Dev

The development environment was created so that we can redeploy easily. Whenever code in the sage-monorepo is merged after PR was reviewed and all checks approved, a GHA job publishes new images tagged with `edge` and the commit SHA for each service in the stack that changed (e.g. the latest image on the [qtl-app package](https://github.com/Sage-Bionetworks/sage-monorepo/pkgs/container/qtl-app) page carries both the `edge` tag and a `sha-…` tag). The dev infra stack points at the `edge` image tag. So we can rerun the latest `deploy-dev` GHA job to redeploy the latest app code, by looking up the SHA of the most recent image using the `edge` tag and the GitHub API.

So, the footer of the dev site will only show the image tag of the `qtl-app` package, which in this case is the commit SHA.

### Stage/Prod

Stage and prod environments point at a specific git tag that is manually added. As described below, when a new git tag is manually created for this app in the sage-monorepo, a GHA job publishes new images tagged with that git tag (listed on the [qtl-app package](https://github.com/Sage-Bionetworks/sage-monorepo/pkgs/container/qtl-app) page). Then, the stage or prod environment variables in the infra repo can be updated to point at that tag. When the changes are merged to the `stage` or `prod` branch, a GHA job will run the `deploy-stage` or `deploy-prod` job accordingly, which will deploy the images tagged with the git tag.

## Dev Deployment

1. When a PR that affects this app is merged to `main` in the sage-monorepo, wait for the [ci job](https://github.com/Sage-Bionetworks/sage-monorepo/actions/workflows/ci.yml) to finish building and publishing images for the affected projects to GHCR.
2. Rerun the last [deploy-dev job](https://github.com/Sage-Bionetworks-IT/qtlexplorer-infra/actions/workflows/deploy-dev.yaml) and wait for the job to successfully update dev deployment. Deployment can be monitored in AWS console in AWS ECS.
3. Confirm that [dev site](https://dev.xqtlexplorer.adknowledgeportal.org/) shows changes from last merged PR.

## Staging Deployment

1. Review the list of existing tags [here](https://github.com/Sage-Bionetworks/sage-monorepo/tags). Identify the next `qtl` tag. For example, if the last `qtl` tag is `qtl/v4.0.0-rc2`, then the next tag will be `qtl/v4.0.0-rc3`. If the last `qtl` tag doesn’t have a release candidate suffix (e.g. `qtl/v4.0.0`), then the next tag will be the first release candidate of a new version (e.g. `qtl/v4.0.1-rc1`). This follows the convention found at [semver.org](https://semver.org/).
2. Create a new git tag in the sage-monorepo:
   - Open devcontainer
   - Checkout the main branch: `git checkout main`
   - Fetch latest changes: `git fetch upstream`
   - Rebase: `git rebase upstream/main`
   - Tag the commit: `git tag qtl/v4.0.0-rc3`
   - Push the tag: `git push upstream tag qtl/v4.0.0-rc3`
3. Wait for sage-monorepo [release GHA job](https://github.com/Sage-Bionetworks/sage-monorepo/actions/workflows/release.yml) to successfully build, tag, and push images to GHCR.
4. Create a new branch and edit `app.py` to set `GHCR_PACKAGE_VERSION` to the new version number (e.g. `4.0.0-rc3`) and not the tag (e.g. `qtl/v4.0.0-rc3`) in 2 places in the code for `stage` and `prod` configurations. Create PR in this [repo](https://github.com/Sage-Bionetworks-IT/qtlexplorer-infra) **to the dev branch**.
5. Merge PR. Wait for [deploy-dev job](https://github.com/Sage-Bionetworks-IT/qtlexplorer-infra/actions/workflows/deploy-dev.yaml) to successfully update dev deployment. Deployment can be monitored in AWS console in AWS ECS.
6. Create PR in this repo **to merge dev into the stage branch**. You can use this [url](https://github.com/Sage-Bionetworks-IT/qtlexplorer-infra/compare/stage...dev).
7. Merge PR. Wait for [deploy-stage GHA job](https://github.com/Sage-Bionetworks-IT/qtlexplorer-infra/actions/workflows/deploy-stage.yaml) to successfully update staging deployment. Deployment can be monitored in AWS console in AWS ECS (see [NOTE on cutover delay](#overview) above).
8. Confirm that [staging site](https://stage.xqtlexplorer.adknowledgeportal.org/) shows new version’s tag in the app footer.

## Production Deployment

1. Go to the staging site and note the tag in the app footer. Identify the `qtl` release tag. For example, if the staging site tag is `qtl/v4.0.0-rc3`, then the release version will be `qtl/release/v4.0.0`.
2. Create a new git tag in the sage-monorepo:
   - Open devcontainer
   - Checkout the main branch: `git checkout main`
   - Fetch latest changes: `git fetch upstream`
   - Rebase: `git rebase upstream/main`
   - Get the commit hash of the existing tag: `git rev-list -n 1 qtl/v4.0.0-rc3`
   - Create a new tag pointing to the same commit: `git tag qtl/release/v4.0.0 {commit hash}`
   - Confirm that the new tag is on the same commit as the previous tag by reviewing the git log: `git log --oneline`
   - Push the tag: `git push upstream tag qtl/release/v4.0.0`
3. Create a PR in this repo **to merge the stage branch into the prod branch**. You can use this [url](https://github.com/Sage-Bionetworks-IT/qtlexplorer-infra/compare/prod...stage).
4. Merge PR. Wait for the [deploy-prod GHA job](https://github.com/Sage-Bionetworks-IT/qtlexplorer-infra/actions/workflows/deploy-prod.yaml) to successfully update prod deployment. Deployment can be monitored in AWS console in AWS ECS.
5. Confirm that [production site](https://xqtlexplorer.adknowledgeportal.org/) shows the same tag in the app footer as the staging site.

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

### qtlexplorer-infra repo: Deploy to Staging

6. **Update qtlexplorer-infra repo to point at hotfix tag**

   Create a new branch from dev in this repo and edit `app.py` to set `GHCR_PACKAGE_VERSION` to the new hotfix version (e.g., `1.0.1-rc1`) in 2 places in the code for `stage` and `prod` configurations.

   ```console
   git checkout dev
   git pull origin dev
   git checkout -b hotfix/update-to-v1.0.1-rc1
   ```

   Edit `app.py` to update `GHCR_PACKAGE_VERSION` for both `stage` and `prod` configurations, then:

   ```console
   git add app.py
   git commit -m "chore: update stage to hotfix v1.0.1-rc1"
   git push origin hotfix/update-to-v1.0.1-rc1
   ```

   Create PR **to the dev branch**.

7. **Deploy to dev**

   Merge PR. Wait for [deploy-dev job](https://github.com/Sage-Bionetworks-IT/qtlexplorer-infra/actions/workflows/deploy-dev.yaml) to successfully update dev deployment.

8. **Deploy to staging**

   Create PR **to merge dev into the stage branch**. You can use this [url](https://github.com/Sage-Bionetworks-IT/qtlexplorer-infra/compare/stage...dev).

   Merge PR. Wait for [deploy-stage GHA job](https://github.com/Sage-Bionetworks-IT/qtlexplorer-infra/actions/workflows/deploy-stage.yaml) to successfully update staging deployment. Deployment can be monitored in AWS console in AWS ECS.

   Confirm that [staging site](https://stage.xqtlexplorer.adknowledgeportal.org/) shows the hotfix version tag in the app footer.

### sage-monorepo: Create Production Release Tag

9. **Tag the production release**

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

### qtlexplorer-infra repo: Deploy to Production

10. **Deploy to production**

    Create a PR **to merge the stage branch into the prod branch**. You can use this [url](https://github.com/Sage-Bionetworks-IT/qtlexplorer-infra/compare/prod...stage).

    Merge PR. Wait for the [deploy-prod GHA job](https://github.com/Sage-Bionetworks-IT/qtlexplorer-infra/actions/workflows/deploy-prod.yaml) to successfully update prod deployment. Deployment can be monitored in AWS console in AWS ECS.

    Confirm that [production site](https://xqtlexplorer.adknowledgeportal.org/) shows the hotfix version tag in the app footer.

### sage-monorepo: Backport to Main

11. **Submit Pull Request in sage-monorepo to backport the fix**

    To ensure the fix is not lost in future releases, submit a backport Pull Request:
    - Source: `upstream/qtl/hotfix/v1.0.1`
    - Target: `upstream/main`

    > [!NOTE]
    > Resolve any merge conflicts that occurred due to changes on main since the original release.
