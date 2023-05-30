# Tests

## General principles

* Any new code/feature should be accompanied by tests.
* Tests should be baked by coverage report done in CodeCov. Any uncovered branch should be understood and tried to be covered if needed. We should aim at the highest coverage as possible.
* Prefer package/module level testing to unit tests. Try to test only with the external API of this scope (if the language allows you to do this and only poke few holes, try it) and only go on the unit test level when this is needed (a complex, local, function). This allows you to assess your API and is a good documentation for anyone who need to use this package.
* We do not encourage TDD, which forces to crystallize the API way too early in the design process. We thus compensate the lack of guided code path testability assurance:
  * by using coverage extensively to ensure that the tests is going through the desired pass.
  * By reversing, the "want" condition, to ensure that the test is failing as expected. It’s also a good time to assess and check that the returned error and log messages make sense.
* Do not test only the happy path, ensure at least one error case, if the method can return an error, is covered. Try to think how you can trigger more error cases with an inconsistent file system state for instance (file being read only when you expect to write to it…).
* One easy way to expand and facilitate adding tests in the future is to use a conjunction of table testing and golden files.
* Apart when bootstrapping a project, the tests should always pass in the main branch.

### Parallel tests

Run your tests in parallel. This ensure also that a test is not potentially impacted by the load on the system, nor by any shared or global state.

Also, try to run the tests in random orders. For instance, in Go, having the table testing as a `map[string]struct{}` helps ensuring we don’t always rely on potential tests state leftovers.

### Race detector

Enable race detection if your language allows it. You should always run first your test without the race detector. Then, you rerun your tests with race detection again.

### Location of the tests

* Unit, package (or module) and integration testing should be in the upstream repository.
* The unit and package tests are in separate files, alongside the code they are actually testing.
* Integration tests should be in a dedicated directory, next to the command line they are testing or external entry point with an explicit "integration tests" name.
* End to end tests should be at the root of one of the project.

Each tests should place any fixtures or third party assets next to the assets, within a `testdata/` subdirectories. More on the actual placement in the table testing case.

> Your project `CONTRIBUTING.md` should mention how to run each kind of tests and how to refresh golden files.

### Files created by the tests

Any files or directories created by the tests should be in a temporary directory, the outcome of running tests should create no new files in the current project tree.

## Table testing

The main approach should be the usage of table testing driven by coverage. Table testing should use a map (or dictionary) of strings to test case objects.

* The string should describe what the tests are actually doing (capitalized). It's a sub-test of a given test.
* The test case itself should be a structure type of the tests input and expected outcomes (if not a golden file).

> In the rest of the document, we are going to call the main test "family test" and sub-test just "test" or "test case".

The usage of table testing allows us to:

1. Easily demonstrates how a component or API is supposed to be and gives a great example of its expectations. It gives clearly the “input/output” contract for a given API. Also, you can easily see how to build your object and which sequence of calls is expected from the API.
1. Easily extends the coverage by adding a new test case. "What if I give this input to trigger that situation, what if I use this fixture to trigger an error…"
1. Quickly parse the various cases and contracts of an API usage "If I give those inputs, I will get back this".
1. Force to factor out commonalities between tests and probably redesign some parts of the behaviour. If the API changes later on, only adapt on test for it, not many.

Any module/package API level should be tested independently, with a corresponding family test. If triggering some edge cases for this family diverges too much from the main family tests, then additional, separate tests are more appropriate. However, when doing this, always think on the additional cost when future enhancements requiring changes to code behaviour, call order or API itself this will impact.

One easy way to expand and facilitate adding tests in the future is to use a conjunction of table testing and golden files.

### Fixture Location

* Fixture assets tree used in a single family test should be placed under `testdata/<family_test_name>/`.
* If a fixtures is specific to only one subtests, it could even be placed under `testdata/<family_test_name>/<subtest_name>`. This could be loaded automatically, based on the family and subtest names by the test code.
* Any shared fixtures between multiple tests can be directly placed under `testdata/`, usually organized with meaningful directory namings.

## Golden testing

Golden files allows to easily compare your expected output to a reference that is checked-in within your codebase. This avoids, in particular with table testing, an expanded "want" content.

This helps also on the maintenance front: we should have an `UPDATE` flag (preferably an environment variable like `<PROJECT>_UPDATE_GOLDEN=1`) to automatically update the references. Then as part of any update with new fields, or simply a new test addition, the maintainer simply update automatically (thus, the tests will pass), run `git diff` to review the changes and ensure that those make sense. Finally, those files are added and committed to become the new reference.

> Your project `CONTRIBUTING.md` should mention how to refresh golden files.

### Golden file location

Similarly to fixtures, golden files are located depending on its impacts:

* `testdata/<test_name>/golden` for simple test name.
* `testdata/<family_test_name>/golden/<subtest_name>`.

`golden` or `<subtest_name>` is a simple file (if the golden file is an unmarshalled structure, or directory).

### Structure golden files

You can serialize/deserialize your expected object and compare against that reference. For readability, the serial format can be yaml.

### Golden tree

When the outcome of an API call is not an object but one of more configured files on disk, then, the golden content is a tree representing files and directories that are created by the method call.

In general, the test will alter the `root` of the system to a temporary directory, and then, compare this with the reference golden tree, ensuring that each folder is created as expected and each files contains the correct permissions and content.

If an update is required, then, this temporary directory content will directly replace the golden tree path after its purge. This ensures there is no leftover on the long term.

> Empty created directories still needs to be checked in it git, which is only tracking files. In general, we touch a `.empty` file as a tracker which is then ignored during the tree comparison.

## Fuzz testing

Fuzz testing should be used when you don’t trust the input of a given function. This allows to easily detect bugs and other misbehaving of your application and can reveal vulnerabilities.

Ideally, your framework will do coverage-based fuzzing, and then use case simplification.

Only fuzz parts where you feel the input can lead to bad behaviour of your application, in particular if you handle the deserialization yourself.

## Benchmarking

In general, we optimize first for maintainability and then for performance. Pick your battle and only optimize where it makes sense, after prooving that this part of the code is impacting very negatively your whole project performance. Basically, bring first data to the table!

Once you fix your performance issues, this is time to build a benchmark of your isolated tests, and track its behaviour with the time. If it regresses significantly, raise it as a failing test.
