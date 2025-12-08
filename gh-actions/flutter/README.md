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
