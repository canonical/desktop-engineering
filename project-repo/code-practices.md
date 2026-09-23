# Code practices

- All new code comes with tests. Fixes not coming with tests is rather the exception than the norm.

- We follow upstream/community formatting conventions for the given technology. For instance. in Go, we tighten it using `gofumt` instead of `gofmt`. In Rust, `rustfmt`.

- The code should always be linting-error free.

- We should not have any warning/error when building a project. Any of those needs to be "clear" (with a comment explaining why we are ignoring this warning).

- Every method have a docstring/annotation explaining what the function does, what it accepts and what it returns. Also, for languages raising exceptions, if any kind of specific exception that this method raises.

- Two code copies are OK, if you start having a third one, it's probably time to generalize/factor it out.

- Always have private interfaces/modules first, and only open them up if you use them. Do not pre-determine that this element should be public because you will use it one day.

- Avoid using global variables in modules. Prefer a struct that embeds the state and that can be mock for other package level tests.

- Commit convention: something I have a less strict opinion about. I think there should always be a description and a short commit title. The commit title can reference the domain of the project this work is acting on. There is some proposal to use Conventional Commits, how do we relate it to non squash commits if we don't follow this?

- Releases are tagged as SEMVER.

- We should keep version 0.x until we are shipping a given product is GA for the Product Manager.

- No premature optimization: maintainability > performance. Write your code to be maintainable (low cyclomatic complexity in code, clear variables, commented code to explain non trivial parts). If then, some code becomes critical and you have a suspicion this part is what is triggering a performance issue, don't assume, prove it first. Measure, analyze, fix.

- Logging: We only allow some restricted levels of logging: Error/Warning/Info/Debug.

  - Default logging level is Warning.

  - Errors are unrecoverable issues, theoretically making the program stop or abort critical tasks that could not be retried.

  - Warning are important information to the administrator when a recoverable task or an unimportant task fails. The normal running execution of a program is expected to display no warning.

  - Info: those are the expected information to the admin looking at high level information for their system `listening on socket <addr>`, `got request <details>`.

  - Debug: low level of detail information, preferably on a per function level, naming the function and incoming arguments. Also, use to differentiate where in the code we are branching in. This is typical "for developer debugging" information level.

  - Opened for discussion (as in general, a little bit less relevant for the desktop): use of structured logging library.

- Early return: try to align code on the left as much as possible. The happy path is on the left, the nested part are particular use case, with early bailing out. Basically, the `else` clause is more the exception than the rule. Functions can be shortened in addition to the readability this gives to the reading flow.
