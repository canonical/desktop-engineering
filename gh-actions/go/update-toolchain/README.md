# Update Go toolchain patch version

Bumps the patch version of the `toolchain` directive of every `go.mod` and `go.work` file found
recursively under `working-directory` to the latest stable patch release of the same minor version
(e.g. `toolchain go1.24.1` → `toolchain go1.24.9`), and opens a pull request with the changes.

- Only the patch version is changed: neither the `go` directive nor the toolchain minor version is
  touched.
- Files without a `toolchain goX.Y.Z` directive (including pre-releases like `go1.25rc1`) are skipped.
- All updated files go into a single commit on `head-branch`, which is force-pushed on every run. If
  a pull request from `head-branch` to `base-branch` is already open, its title and body are
  updated; otherwise a new one is created.
- If nothing needs updating, nothing is committed.
- A job summary lists changed files and the pull request link, or reports a dry run or no changes.
- The commit message and pull request title are `deps(go): bump toolchain to goX.Y.Z`.

## Usage

```yaml
name: Update Go toolchain

on:
  schedule:
    - cron: "0 6 * * 1"
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  update-toolchain:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: canonical/desktop-engineering/gh-actions/go/update-toolchain@main
```

The checked out commit must be the tip of `base-branch`, otherwise the action fails rather than
opening a pull request containing unrelated commits. The repository must be checked out at
`GITHUB_WORKSPACE`, and `working-directory` must be within it. Except in dry runs, unstage any
existing changes before invoking the action. Only updated toolchain files are passed to
`add-paths`; other unstaged and untracked files are excluded from the commit. Any existing
edits within an updated file are included. Paths containing commas are rejected because
the upstream `add-paths` input treats commas as separators.

Commits and pull requests are created through
[peter-evans/create-pull-request@v8](https://github.com/peter-evans/create-pull-request) with
`sign-commits: true`. Commits are GitHub-verified when using the default `GITHUB_TOKEN` or
a GitHub App bot token. Personal access tokens can create pull requests, but their commits
are not signed. SSH signing keys are not used.

Only `contents: write` and `pull-requests: write` are required for the default token, as shown
above. `id-token: write` is **not required**: it enables OIDC token requests, which this action
does not use. Also enable **Allow GitHub Actions to create and approve pull requests** in the
repository's Actions settings when using `GITHUB_TOKEN`.

Pull requests created with the default `GITHUB_TOKEN` do not trigger other workflows. Pass a
GitHub App or personal access token as `github-token` if CI should run on the pull request.

## Inputs

| Name | Default | Description |
|---|---|---|
| `working-directory` | `.` | Directory in which to recursively look for `go.mod` and `go.work` files. |
| `ignore` | `*/vendor/*`<br>`*/testdata/*`<br>`*/.git/*` | Newline-separated globs of paths to ignore (see below). Setting it replaces the defaults; set it to an empty string to ignore nothing. |
| `github-token` | `${{ github.token }}` | Token used to push and open the pull request. Requires `contents: write` and `pull-requests: write`. |
| `base-branch` | repository default branch | Branch the pull request targets. |
| `head-branch` | `deps/auto-go-toolchain` | Branch the changes are force-pushed to. |
| `dry-run` | `false` | Only update the files and set the outputs, without committing, pushing or opening a pull request. |

### Ignoring paths

Each `ignore` pattern is passed to `find -path`, so it is matched against the whole path relative to
`working-directory`, prefixed with `./`, and `*` also matches `/`. Directories that match are not
descended into. For example:

```yaml
ignore: |
  */vendor/*
  ./tools/go.mod
  ./examples
```

## Outputs

| Name | Description |
|---|---|
| `versions` | Space-separated list of the toolchain versions files were updated to. Empty if nothing was updated. |
| `pull-request-url` | URL of the created or updated pull request. |

## Tests

The test workflow generates disposable module and workspace files under `RUNNER_TEMP`.
It stubs the Go release response, so tests require neither network access nor maintained
fixture files. Runs use `dry-run: true` and an empty token; `git` and `gh` are stubbed to
fail if any publishing command is attempted.
