# Recommended GitHub repository settings

In order to encourage all contributors to follow the recommended [review process](review-process.md), the repository settings listed in the following sections should be applied.

## Pull requests

The settings listed below should be enabled/disabled as indicated. All other settings can be chosen based on project-specific needs.

- [x] Allow merge commits (default commit message: "Pull request title and description")
- [ ] Allow squash merging
- [ ] Allow rebase merging

- [x] Automatically delete head branches


## Branch protection rules

The `main` branch (and any other public development branches from which releases are created) should be protected with by a corresponding set of rules.
The settings listed below should be enabled/disabled as indicated. All other settings can be chosen based on project-specific needs.

- [x] Require a pull request before merging
    - [x] Require approvals
    - [x] Dismiss stale pull request approvals when new commits are pushed
- [x] Require status checks to pass before merging
- [x] Require conversation resolution before merging
- [x] Require signed commits
