# Check source formatting

This folder contains both a script (`format-source.sh`) and a gh-action
(`format.yaml`) for checking and fixing the format of the source code,
both locally during the commit operation and in the CI steps during
a `git push`.

## Configuring

Just copy the `format.yaml` file to the `.github/workflows/` folder and
the `format-source.sh` script to the project root folder. By default,
it will search recursively in all the folders for `.c` and `.h` files;
but it is possible to define an environment variable called SOURCE_PATHS,
which should contain all the folders containing source files, separated
by spaces. This environment variable will be set from the action input
`inputs.sourcePaths`.

Also, in your system, you can edit the `.git/hooks/pre-commit` script:

    #!/bin/sh
    ./format-source.sh pre-commit

and give to it execution permissions.

Now, every time a `commit` is done, the source code will be checked and,
if it doesn't follow the desired format, the commit operation will be
aborted.

Just executing the `format-source.sh` script from the command line will
automatically format the source following the style defined in the
`.clang-format` file (or the `clang-format` defaults if it doesn't exist).
