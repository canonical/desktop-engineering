# Common GitHub Actions

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
      - uses: canonical/desktop-engineering/gh-actions/common/weblate-l10n@REVIEWED_COMMIT_SHA
        with:
          github-token: ${{ secrets.DESKTOP_GH_BOT_TOKEN }}
          ssh-signing-private-key: ${{ secrets.DESKTOP_GH_BOT_SSH_SIGNING_PRIVATE_KEY }}
          generation-command: |
            melos gen-l10n
            melos sync-desktop-titles
```

#### Setup

1. Set `DESKTOP_GH_BOT_TOKEN` to a dedicated bot PAT with Contents read/write
   access to the upstream repository. The bot needs push access, and the PR
   must allow maintainer edits. PAT pushes let normal PR CI run again.
2. Set `DESKTOP_GH_BOT_SSH_SIGNING_PRIVATE_KEY` to an unencrypted SSH private key.
   Register its public key as a **signing key** on the same bot account.
3. Adjust `generation-command` for your project. It must not create commits or
   move `HEAD`.

#### Behavior

- Allowed translations: `.arb` beneath any `l10n` directory and `.html` anywhere.
  Allowed generated files: `.dart` beneath `l10n` and `.desktop` anywhere.
- Other paths, symlinks, submodules, and newly executable files are rejected
  before setup. Customize paths with newline-separated regular expressions in
  `translated-file-patterns` and `generated-file-patterns`; never allow generator
  scripts or configuration. For custom translation formats, also update the
  workflow's `pull_request_target.paths` filter above (or remove that filter).
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
  -s gh-actions/common/weblate-l10n/tests -p 'test_*.py' -v
```
