# Flutter GitHub Actions

## Example Usage

### With the `workflow_call` actions as-is

```yaml
name: My Workflow

on:
  workflow_dispatch:
  push:

jobs:
  melos-matrix:
    uses: canonical/desktop-engineering/gh-actions/flutter/melos-matrix.yaml@main
    with:
      os: ${{ matrix.os }}
    strategy:
      matrix:
        os: ["ubuntu-24.04"]

  # or
  standalone-melos:
    uses: canonical/desktop-engineering/gh-actions/flutter/melos.yaml@main

  # Or if the repo doesn't use melos:
  # flutter-actions:
  #   uses: ./.github/workflows/flutter.yaml
```

### With the composite actions for more specific workflows

```yaml
name: My Workflow

on:
  workflow_dispatch:
  push:

jobs:
  my-workflow:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: canonical/desktop-engineering/gh-actions/flutter/setup@main
      - run: flutter doctor
      - run: flutter test
      # Flutter and FVM are interchangeable here since the setup action installs
      # both on the same Flutter version
      - run: fvm flutter doctor
      - run: fvm flutter test
```

#### FVM behavior

A `.fvmrc` file at the repository root is **mandatory** - the setup action
fails when it is missing. Pin a Flutter version with `fvm use <version>` and
commit the resulting `.fvmrc`. The Flutter version is always the one pinned in
`.fvmrc`, keeping all repositories on the same approach.

FVM is installed to `$HOME/fvm/bin` (FVM 4.x layout) and that directory is
appended to `$GITHUB_PATH`.

#### Melos behavior

Melos is only set up when the repository contains a `melos.yaml`, and the setup
is opinionated about the version to keep all repositories on the same approach:

1. The version is parsed from the `melos` entry in `pubspec.lock`.
2. If there is no locked version, the setup **fails** - melos is never floated
   on `latest`, because an untested melos release breaking CI causes
   hard-to-debug issues. Add melos to your dev dependencies and commit
   `pubspec.lock`.

## Regenerating Weblate localizations

The `weblate-l10n` action regenerates localization files on Weblate fork PRs,
signs the generated commit, and pushes it back to the PR branch.

Use `pull_request_target` and replace `REVIEWED_COMMIT_SHA` with a full, reviewed
commit SHA. Keep the author and sender checks below to avoid bot-triggered loops
while allowing maintainers to reopen PRs.

```yaml
name: Regenerate Weblate localizations

on:
  pull_request_target:
    types: [opened, synchronize, reopened]
    paths:
      - '**/*.arb'
      - '**/*.html'

permissions:
  contents: read
  pull-requests: read

concurrency:
  group: weblate-l10n-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  regenerate:
    if: >-
      github.event.pull_request.user.login == 'weblate' &&
      github.event.pull_request.head.repo.owner.login == 'weblate' &&
      (github.event.action != 'synchronize' || github.event.sender.login == 'weblate')
    runs-on: ubuntu-latest
    steps:
      - uses: canonical/desktop-engineering/gh-actions/flutter/weblate-l10n@REVIEWED_COMMIT_SHA
        with:
          github-token: ${{ secrets.DESKTOP_GH_BOT_TOKEN }}
          ssh-signing-private-key: ${{ secrets.DESKTOP_GH_BOT_SSH_SIGNING_PRIVATE_KEY }}
```

#### Setup

1. Set `DESKTOP_GH_BOT_TOKEN` to a dedicated bot PAT with Contents read/write
   access to the upstream repository. The bot needs push access, and the PR
   must allow maintainer edits. PAT pushes let normal PR CI run again.
2. Set `DESKTOP_GH_BOT_SSH_SIGNING_PRIVATE_KEY` to an unencrypted SSH private key.
   Register its public key as a **signing key** on the same bot account.

#### Behavior

- Generation always runs `melos gen-l10n`; it must not create commits or move
  `HEAD`.
- Allowed translations: `.arb` beneath any `l10n` directory and `.html` anywhere.
  Allowed generated files: `.dart` beneath `l10n` and `.desktop` anywhere.
- Other paths, symlinks, submodules, and newly executable files are rejected
  before setup. Keep the workflow's `pull_request_target.paths` filter aligned
  with the fixed translated source formats above, or remove that filter.
- Generation fails if it creates any ignored file, even if force-staged with
  `git add -f`. Ignored artifacts already present after Flutter setup are excluded.
- No generated changes means no signing or push. If the PR branch changes
  during the run, the push fails instead of overwriting it; retry on the current
  PR revision.

#### Testing the action

PRs changing `weblate-l10n` or its test workflow automatically run the tests.
To run locally, install Python 3, Node 24, Git, OpenSSH, and Bash; no Flutter or
GitHub secrets are needed. Set `NODE` to use a different Node executable.

```bash
python3 -m venv /tmp/weblate-tests
/tmp/weblate-tests/bin/python -m pip install PyYAML==6.0.2
PYTHONDONTWRITEBYTECODE=1 /tmp/weblate-tests/bin/python -m unittest discover \
  -s gh-actions/flutter/weblate-l10n/tests -p 'test_*.py' -v
```

