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

