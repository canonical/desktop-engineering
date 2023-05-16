# Review process

## General principles

We don't allow general push to main branch. The only allowed push to main is tag push for a release version. Very optionally, some emergency fix are allowed, but a good reason is needed to flex out and bypassing a pull request.

> Even in those cases, it’s still better to go through a pull request to ensure that automated tests and checks are running, even if it’s merged without further reviews.

Any Pull Requests should have at least one reviewer. This is our way to ensure quality and double checking on what we produce as a team. This impacts any domains:

* Projects we are upstream for or contributing to
* Packaging (snaps or debian) changes

When we contribute to projects we are not the upstream, of course, we follow upstream's way of doing their review. The guidelines below can still help targeting and ensuring that any submission made by a Canonical contributor is seen as high quality, trusted, change from the get-go.

Finally, if some changes have been done in a pair-programming context, those can be considered as a review already. However, sanity checks (see the first steps) are still expected to be proceeded by both parties before merging.

### Policies and guidances

The whole results of those guidances is really to ease code and project maintainability in the long run. Double questioning an approach or giving suggestions should always follow this trail of thoughts: How is it going to make the code easier to understand and maintain? How is the code is going to be more robust? Can we avoid premature optimization towards that goal?

* Always prefer to land multiple small PRs, with unrelated than a big PR with multiple changes mixed in. Both your future you and the reviewer will thank you.
* As a consequence, we don’t encourage "long-lived feature branch".
* Any new code and fixes should be accompanied with new or modified existing tests. Only few crashers fix really hard to reproduce are acceptable without further automated tests. If this is the case, please ensure the description reflects this.
* Any commits merged in main branch needs to pass tests. This is our mainline. You can split your changes in multiple, more discrete, modifications to give additional context if you need to dig into the git history later on.
* Reviewing a change is serious business. The general "LGTM" is more the exception than the rule. Comments should be encouraged and always seen as positive feedback to push our understanding of what we are trying to resolve.
* When there are multiple reviewers on a PR, please pay attention to the comments and answers of your peers! This helps building shared understanding of the code and you are not protected against learning a few new interesting tricks or concepts. :)
* Do not let PR opened without activity for more than 3 days. Try to be responsive within a day for external contributor PR. Rotten branches should be either worked on or deleted. This helps ensuring that the repository has an easy and actionable PR review list.
* Automated PR for dependency updates should be looked at with scrutiny: it’s not only because tests are passing that it’s fine to merge them. Look at the upstream changelog/commits, assess the impact, see if we can benefit from the changes and reduce technical debt. If any changes are required to have the tests passing again, those changes should be added to the same branch updating the dependency directly.

### Merge workflow

We should use the merge commit workflow (not squash and merge). The history of each branch should make sense and not more "fixup" commits should be there.

However, for better readability of the mainline, the merge commit in the mainline should follow [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/). On Github, this can be enforced [on a project level](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/configuring-commit-merging-for-pull-requests). TODO: have a document defining what to configure in every new github project (webhook for Jira, merge commit + default commit template, automated merged branch deletion).

## Process

First, don’t be afraid to comment and iterate! However, when you start to engage in a PR, the expectation is that you keep being responsive. A PR should not be stalled.

1. The PR should always be opened as a draft to not notify the reviewers from automation. Ensure you have the description of the changes readable and understandable by the reviewing. The PR is linked to a Jira card, using **UDENG-XXX** in the description so that Jira links against it.
1. The submitter looked at the diff (it can happens that you left a debug print statement or did an accidental `git add`, please reread yourself by giving a quick visual scan).
1. The submitter waits and check for the CI feedback to give a pass (linting, testing, building, automated generation…). Static security check tool (part of linting if possible) is part of that stage. Feel free to ask for help before a formal review if anything don’t pass (like tests) and you don’t have an idea on how to fix it. It needs to be set in the description that the tests don’t pass and ping one of the team member.
   > You should squash fixes at this staged with the relevant commits.
1. Code coverage report should be posted then and any significant drop should be questioned or commented.
1. Request for review by marking the PR as ready for review. The team that is responsible for this PR (automatically pre-populated in CODEOWNERS) will be notified.
    > If Another member of the owning team has done pair programming, all authored reviews again the diff and can approve directly.
1. Another member of the team does a code review:
    * Each suggestion is added where they are inside the diff as a comment.
        > If the diff is huge, using the “mark as read” checkmark on Github helps (launchpad does not have this unfortunately).
    * Code coverage is looked at to see if there are new spots in the code that is not covered by changes, which could be covered.
    * Commit history rephrase/changes suggestion should be put in the global comment suggestion.
        > If there are too many changes or strong disagreement on the approach, feel free to jump on a call, or even start some pair-programming session.
1. Then approved/request changes are posted by the reviewer.

### If some changes are required

1. The submitter either argues on each comment or gives a 👍 on each suggestion to ensure those are acknowledged.
1. Any changes should be appended to the commit history, ready to be squashed in existing commits (so, per domain). Keep them as individual commits for now to ease the rereview (most of tools don’t have a good diff on diff view).
1. The submitter assess CI test results, code coverage and re-request a review.
1. The reviewer looks at the changes, and resolves himself any fixed comments (or agree with the arguments from the submitter).
   > It’s always the person opening a comment and not the submitter that resolves the comments once happy with this particular change.

The cycle goes on if there are further comments or still some opened one. Once all comments are resolved, the reviewer would approve.

### Finale merge

1. The submitter will squash the optional additional commits and force push.
1. The submitter does a last look is done on the diff, test results, coverage.
1. The submitter is in charge of merging the changes by pressing the merge button.

> Note: The finale merge steps may be proceeded by the submitter if we are in a hurry. However, it’s preferable to let that responsability to the submitter.
