# Review process

## General principles

In general direct pushes to the `main` branch are not allowed, and Pull Requests should be used. The only allowed push to `main` is to push the tag for a new release. Optionally, the direct push of an emergency fix to `main` may be allowed, but a good reason is needed for bypassing the pull request requirement.

> Even in those cases, it’s still better to go through a pull request to ensure that automated tests and checks are running, even if it’s merged without further reviews.

Each pull request should have at least one reviewer. This is our way of ensuring quality and double-checking on what we produce as a team. This applies both to the projects we are the upstream for or we are a contributor to, as well as to packaging (snap or .deb) changes.

When contributing to the projects we are not the upstream for, we of course follow upstream's methodology for code reviews. However, the guidelines below can still help ensure that any submission made by a Canonical contributor is of high quality right from the get-go.

If a change has been done in a pair-programming context, that can be considered as already reviewed. However, sanity checks (see the first steps) are still expected to be carried out by both parties, before merging.

### Policies and guidelines

The aim of these guidances is to ease the maintainability of code and the project as a whole, in the long run. Double questioning an approach or providing suggestions should always follow this trail of thoughts: How will it make the code easier to understand and maintain, and more robust? Can we avoid premature optimisations towards that goal?

* Always prefer to land multiple small pull requests, rather than a large pull request with multiple unrelated changes mixed in. Both your future self and the reviewer will thank you.
* As a consequence, we don’t encourage "long-lived feature branch".
* Any new code and fixes should be accompanied with new or modified existing tests. Only fixes for rare crashes that are exceptionally difficult to reproduce are acceptable without accompanying automated tests. If that is the case for your particular fix, please ensure the description reflects this.
* Any commits merged in the `main` branch need to pass the tests. This is our mainline. You can split your changes into multiple, more discrete modifications, so as to help give additional context when one needs to dig into the git history later on.
* Reviewing a change is serious business. A generic "LGTM" should be more the exception than the rule. Comments are encouraged and should be seen as positive feedback to broaden our understanding of the issue at hand. Accordingly, the commenter should strive to make their feedback as constructive as possible.
* When there are multiple reviewers on a PR, please pay attention to the comments and answers of your peers! This helps building shared understanding of the code. All of us could always learn something new. :-)
* Try to not let an open pull request remain without activity for more than 3 days. Especially, try to be responsive within a day for contributions from external contributors. Stale branches should be either worked on or deleted. This helps ensure that the repository has an easy and actionable pull request review list.
* Automated pull requests for dependency updates should be looked at with scrutiny: tests passing does not necessarily imply that the pull request is good to merge. Examine at the upstream changelog and/or commit logs, and assess the impact to see if we would benefit from the changes, and generally aim to reduce technical debt. If any changes are required to make the tests pass again for such a pull request, those changes should be added to the very same branch, so that merging the pull request would not leave the tests broken.

### Merge workflow

We should use the **merge commit workflow** (not squash and merge). The history of each branch should make sense on its own, with few or no "fixup" commits.

Individual commits do not follow [conventional commits][convcommits] and are free form. However, for better readability of the mainline, the merge commit in the mainline should follow [conventional commits][convcommits].

For this, the PR title should be of the form: `<type>(<scope>): <subject>`. The scope is optional. The first comment will be the commit body and needs to reference any associated JIRA card on the last line, separated by a blank line.

The accepted `types` are:

* `docs`: Documentation only changes
* `feat`: A new feature
* `fix`: A bug fix
* `refactor`: A code change that neither fixes a bug nor adds a feature (nor add bugs)!
* `misc`: A miscellaneous change that doesn't fit any of the other cases, e.g. build system or CI changes, dependency updates, code formatting changes, or changes to the test suite. Providing a `scope` is mandatory.

## Process

Don't hesitate to comment and reiterate! When you engage with a pull request, the expectation is that you remain responsive, and not let the pull request go stale.

1. Team members should [sign their commits](https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-commits). If community contributors are unable to sign their commits for any reason, the reviewer should sign their commits before merging.
1. The pull request should always be opened as a draft, to avoid notifying the reviewers before the tests pass and the pull request is fully ready for review. Ensure the description of changes is readable and understandable by prospective reviewers. The pull request should be linked to a Jira card, using `UDENG-XXX` in its description, so that Jira links against it.
1. The pull request diff should be examined by the submitter - it may happen that a debug print statement was left in, or a non-related change was accidentally `git add`ed. Please at least do a quick visual scan to help catch such potential issues/typos.
1. The submitter should wait and check for the CI feedback to indicate a pass (linting, testing, building, automated generation, etc.). Static security check tool (part of linting if possible) is part of that stage. Feel free to ping a team member to ask for help before a formal review, if something doesn’t pass (like tests) and you don’t have any ideas on how to fix it. In such cases, the pull request description should mention that the tests don’t pass.
   > You should squash fixes at this staged with the relevant commits.
1. Code coverage report should be posted, and any significant drop in coverage should be questioned or commented on.
1. Request for review by marking the pull request as ready for review. The team that is responsible for this pull request (automatically pre-populated in `CODEOWNERS`) will be notified.
   > If the code change was developed in pair programming with another member of the owning team, the authors of the change can approve the pull request directly, after looking over the diff to make sure it's generally in good shape.
1. Another member of the team does a code review:
   * Suggestion are to be as comments for the corresponding line(s) in the diff.
     > If the diff is very large, using the "mark as read" check-mark on GitHub can help. Launchpad currently does not have a similar feature, unfortunately.
   * Code coverage is to be examined to see if there are new areas in the code that are not covered by the changes, which could have been covered.
   * Suggestions for revising/rewording history of the pull request's commits should be put in the general comment section.
     > If there are too many changes or strong disagreement on the approach, feel free to jump on a call, or even start a pair programming session.
1. The reviewer approves the pull request or requests further changes.

### If changes are required

1. The submitter either argues on each comment or gives a 👍 on each suggestion to ensure those are acknowledged.
1. Any changes should be appended to the commit history, ready to be squashed into potential relevant existing commits. The new changes should be kept as separate commits for the duration of the review, to ease further reviews, as most tools don’t have a good diff-of-diffs view.
1. The submitter assesses the CI test results and code coverage, and requests another review.
1. The reviewer examines the changes, and resolves any fixed comments or agrees with the arguments from the submitter.
   > It’s always the person opening a comment, **not** the submitter of the pull request, that should resolve the comments, once they are happy with the particular change.

This cycle is repeated if there are further comments or if some are still left open. Once all comments are resolved, the reviewer should approve.
Finally, the submitter should merge the changes by clicking the merge button.

> Note: The final merge steps may be proceeded by the reviewer if we are in a hurry. However, it’s preferable to allow the submitter to do the actual merging, as an additional way of acknowledging their work and enjoying the dopamine boost. :-)

[convcommits]: https://www.conventionalcommits.org/en/v1.0.0/
