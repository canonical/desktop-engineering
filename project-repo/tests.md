# Tests

## General principles

* Any new code/feature should be accompanied by tests.
* Tests should be baked by coverage report done in CodeCov. Any uncovered branch should be understood, and covered if needed. We should aim for achieving the highest coverage possible.
* Prefer package/module level testing to unit tests. Try to test only with the external API of this scope (if the language allows you to do this and only poke few holes, try it), and only go on the unit test level when this is needed (a complex, local, function). This approach allows you to assess your API, and is a good documentation for anyone who needs to use this package.
* We do not encourage TDD, which forces crystalising the API way too early in the design process. We thus compensate the lack of guided code path testability assurance by
  * using coverage extensively to ensure that the tests are going through the desired pass; and
  * reversing, the "want" condition, to ensure that the test is failing as expected. It’s also a good place to assess and check that the returned error and log messages make sense.
* Do not test only the happy path, and ensure that at least one error case - if the method can return an error - is covered. For instance, try to consider how you can trigger more error cases with an inconsistent filesystem state, e.g. a file being read-only when you are expected to write to it, etc.).
* One easy way to expand and facilitate adding tests in the future is to use a combination of table testing and golden files.
* Other than when bootstrapping a project, the tests should always pass in the main branch.

### Parallel tests

Run your tests in parallel. This in part helps check that a test is not potentially impacted by the load on the system, nor by any shared or global state.

Also, try to run the tests in random order. For instance, in Go, implementing table testing with a `map[string]struct{}` helps ensure we don’t always rely on potential leftover test state.

### Race detector

Enable race detection if your language supports it. You should always first run your test without the race detector. Then, re-run your tests with race detection enabled.

### Location of the tests

* The unit, package (or module), and integration testing should be in the upstream repository.
* The unit and package tests are in separate files, alongside the code they are actually testing.
* Integration tests should be in a dedicated directory, next to the command line they are testing, or an external entry point with an explicit "integration tests" name.
* End-to-end tests should be at the root of the project.

Each test should place any fixtures or third party assets next to the assets, within a `testdata/` subdirectory. More on the actual placement in the table testing case.

> Your project's `CONTRIBUTING.md` should mention how to run each kind of test and how to refresh golden files.

### Files created by the tests

Any files or directories created by the tests should be in a temporary directory, and running tests should not create any new files in the current project tree.

## Table testing

The main approach should be the usage of table testing driven by coverage. Table testing should use a map (or dictionary) of strings to test case objects.

* The string should describe what the tests are actually doing (capitalized). It's a sub-test of a given test.
* The test case itself should be a structure type of the tests input and expected outcomes (if not a golden file).

> In the rest of the document, we are going to call the main test "family test" and sub-test just "test" or "test case".

The use of table testing allows us to:

1. Easily demonstrate how a component or API is supposed to be, giving a great example of its expectations. It outlines clearly the “input/output” contract for a given API, and additionally allows one to easily see how to build an object and which sequence of calls is expected from the API.
1. Easily extends the coverage by adding a new test case. "What if I give this input to trigger that situation, what if I use this fixture to trigger an error, etc."
1. Quickly parse the various cases and contracts of an API usage. "If I give those inputs, I will get back this."
1. Force factoring out commonalities between tests and perhaps re-design some parts of the behaviour. If the API changes later on, only adapt one test for it, not many.

Any API level module/package should be tested independently, with a corresponding family test. If triggering some edge cases for this family diverges too far from the main family tests, then additional, separate tests are more appropriate. However, when doing this, always consider the additional cost/impact this might have on future enhancements requiring changes to code behaviour, call order, or the API itself.

One easy way to expand and facilitate adding tests in the future is to use a combination of table testing and golden files.

### Fixture location

* The fixture assets tree used in a single family test should be placed under `testdata/<family_test_name>/`.
* If a fixture is specific to only one sub-test, it could even be placed under `testdata/<family_test_name>/<subtest_name>`. This could be loaded automatically, based on the family and sub-test names, by the test code.
* Any shared fixtures between multiple tests can be directly placed under `testdata/`, usually organized with meaningful directory namings.

## Golden testing

Golden files allow easily comparing the expected output to a reference that is checked in within the code-base. This avoids, in particular with table testing, an expanded "want" content.

This also helps on the maintenance front: there should be an `UPDATE` flag (preferably an environment variable like `<PROJECT>_UPDATE_GOLDEN=1`) to automatically update the references. Then, as part of any update with new fields, or simply a new test addition, the maintainer simply does the update automatically - so that the tests would pass - and runs `git diff` to review the changes and ensure they make sense. Finally, these files are added and committed to become the new reference.

> Your project's `CONTRIBUTING.md` should mention how to refresh golden files.

### Golden file location

Similarly to fixtures, golden files are located depending on their impact:

* `testdata/<test_name>/golden` for simple test name.
* `testdata/<family_test_name>/golden/<subtest_name>`.

`golden` or `<subtest_name>` is a simple file (if the golden file is an unmarshalled structure, or directory).

### Structure of golden files

You can serialize/deserialize the expected object and compare it against the reference. For readability, the serial format can be yaml.

### Golden tree

When the outcome of an API call is not an object, but one or more configured files on the disk, then the golden content is a tree representing the files and directories created by the method call.

In general, the test will alter the `root` of the system to a temporary directory, then compare it with the reference golden tree, ensuring that each folder is created as expected, and each file has the correct permissions and contents.

If an update is required, then, the contents of this temporary directory will directly replace the golden tree path after its purge. This ensures there are no leftovers in the long term.

> Empty created directories still need to be checked into git. But git only tracks non-empty directories, so in general, we touch a `.empty` file as a tracker, which should then be ignored during tree comparisons.

## Fuzz testing

Fuzz testing should be used when the input of a given function is not trusted. This allows to more easily detect bugs and other misbehaviours of the application, and can reveal vulnerabilities.

Ideally, the framework in use will do coverage-based fuzzing, and then use case simplification.

Only fuzz parts where you feel the input can lead to bad behaviour of your application, in particular if you handle the deserialization yourself.

## Benchmarking

In general, we optimise for maintainability first, then for performance. Pick your battle, and only optimise where it makes sense, after prooving that this part of the code is impacting very negatively the whole project's performance. Basically, bring some data to the table first!

Once the performance issues are fixed, it's time to build a benchmark of isolated tests, and track its behaviour over time. If it regresses significantly, raise it as a failing test.
