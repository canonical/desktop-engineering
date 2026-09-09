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

#### Inputs

| Input             | Description                                                        | Default                            |
| ----------------- | ------------------------------------------------------------------ | ---------------------------------- |
| `flutter-version` | The Flutter version to force                                       | Version determined by FVM (`.fvmrc`) |
| `fvm-version`     | The FVM version to install (passed to the FVM installer)           | Latest                             |

#### FVM behavior

The setup action only installs FVM when the repository contains an `.fvmrc` file
or when `flutter-version` is forced via the input. Bare `fvm install` without an
`.fvmrc` fails hard in FVM 4.x (exit 65), so for repositories without `.fvmrc`
the FVM steps (including `FVM Flutter Doctor`) are skipped and no `fvm` binary
is available — use plain `flutter` commands in that case.

FVM is installed to `$HOME/fvm/bin` (FVM 4.x layout) and that directory is
appended to `$GITHUB_PATH`.

Without an `.fvmrc`, Flutter itself is still installed: the version forced via
`flutter-version`, or the latest stable release when the input is unset.

#### Melos behavior

Melos is only set up when the repository contains a `melos.yaml`, and the setup
is opinionated about the version to keep all repositories on the same approach:

1. The version is parsed from the `melos` entry in `pubspec.lock`.
2. If there is no locked version, the setup **fails** - melos is never floated
   on `latest`, because an untested melos release breaking CI causes
   hard-to-debug issues. Add melos to your dev dependencies and commit
   `pubspec.lock`.

Note that the globally activated version is what a direct `melos` call on PATH
uses; `dart pub global run melos` inside a repo that also has melos in its dev
dependencies resolves the workspace's locked version instead.
