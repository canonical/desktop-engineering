# Contributing to PROJECT_TODO

A big welcome and thank you for considering contributing to PROJECT_TODO and Ubuntu! It’s people like you that make these projects a reality for users in our community.

By following these guidelines, you help make the contribution process easy and effective for everyone involved. It also communicates that you agree to respect the time of the developers managing and developing this project. In return, we will reciprocate that respect by addressing your issue, assessing your proposed changes, and helping you finalize your pull requests.

These are mostly guidelines, not rules. Use your best judgment, and feel free to propose changes to this document in a pull request.

## Table of contents

* [Code of conduct](#code-of-conduct)
* [Getting started](#getting-started)
* [Issues](#issues)
* [Pull requests](#pull-requests)
* [Contributing to the code](#contributing-to-the-code)
* [Contributing to the documentation](#contributing-to-the-documentation)
* [Contributor license agreement](#contributor-license-agreement)
* [Getting help](#getting-help)

## Code of conduct

We take our community seriously by holding ourselves and other contributors to high standards of communication. As a contributor to this project, you agree to uphold our [Code of Conduct](https://ubuntu.com/community/code-of-conduct).

## Getting started

Contributions are made to this project through issues and pull requests (PRs). A few general guidelines that cover both:

* To report security vulnerabilities, use the advisories page of the repository and not a public bug report. You can use [launchpad private bugs](https://bugs.launchpad.net/ubuntu/+source/PROJECT_TODO/+filebug) which is monitored by our security team. On an Ubuntu machine, it’s best to use `ubuntu-bug PROJECT_TODO` to collect relevant information. FIXME: snap?
* Search for existing issues and PRs on this repository before creating your own.
* We work hard to makes sure issues are handled in a timely manner but, depending on the impact, it could take a while to investigate the root cause. A friendly ping in the comment thread to the submitter or a contributor can help draw attention if your issue is blocking.
* If you've never contributed before, see [this Ubuntu community page](https://ubuntu.com/community/docs/contribute) for resources and tips on how to get started.

### Issues

Issues should be used to report problems with the software, request a new feature, or discuss potential changes before a PR is created. When you create a new issue, a template is loaded that guides you through collecting and providing the information we need to investigate.

If you find an issue that addresses the problem you're having, add your own reproduction information to the existing issue rather than creating a new one. Adding a [reaction](https://github.blog/2016-03-10-add-reactions-to-pull-requests-issues-and-comments/) can also help by indicating to our maintainers that a particular problem is affecting more than just the reporter.

### Pull requests

PRs are always welcome if you want to directly contribute a fix or improvement to the software. In general, PRs should:

* Only fix/add the functionality in question **OR** address wide-spread whitespace/style issues, not both.
* Add unit or integration tests for fixed or changed functionality.
* Address a single concern by changing the fewest lines possible.
* Include documentation in the repo or on our [docs site](https://github.com/canonical/PROJECT_TODO/wiki).
* Be accompanied by a complete pull request template (loaded automatically when a PR is created).

For changes that address core functionality or would require breaking changes (e.g. a major release), it's best to open an issue to discuss your proposal first. This is not required but it can save time during the PR review process.

In general, we follow the ["fork-and-pull" Git workflow](https://github.com/susam/gitpr). To create a PR using this workflow:

1. Fork the repository to your own GitHub account
1. Clone the project to your machine
1. Create a branch locally with a succinct but descriptive name
1. Commit changes to the branch
1. Follow any formatting and testing guidelines specific to this repo
1. Push changes to your fork
1. Open a PR in our repository and follow the PR template so that we can efficiently review the changes.

> [!NOTE]
> PRs trigger unit and integration tests with and without race detection, linting and formatting validations, static and security checks, freshness of generated files verification. All the tests must pass before merging in main branch.

## Contributing to the code

### Required dependencies

TODO

### Building and running the binaries

TODO

### About the test suite

The project includes a comprehensive test suite made of unit and integration tests. All the tests must pass before the review is considered. If you have troubles with the test suite, feel free to mention it in your PR description.

TODO

The test suite must pass before merging the PR to our main branch. Any new feature, change or fix must be covered by corresponding tests.

### Code style

This project follow the TODO code-style. For more informative information about the code style in use, check:

* For Go: <https://google.github.io/styleguide/go/>
* For Flutter: <https://github.com/flutter/flutter/wiki/Style-guide-for-Flutter-repo>
* For Rust: TODO

## Contributing to the documentation

You can contribute to the documentation in various ways.

At the top of each page in the documentation, there is a Give feedback button. If you find an issue in the documentation, clicking this button will open an Issue submission on GitHub for that specific page.

For more significant changes to the content or organization of the
documentation, you should create your own fork and follow the steps outlined in
the section on [pull requests](#pull-requests).

### Required dependencies

TODO

### Building the documentation

TODO

### Testing the documentation

TODO

## Contributor license agreement

You are required to sign the [Contributor License Agreement](https://ubuntu.com/legal/contributors) (CLA) in order to contribute to this project.

An automated test is executed on PRs to check if the CLA has been accepted.

This project is covered by [THIS LICENSE](LICENSE).

## Getting help

Join us in the [Ubuntu Community](https://discourse.ubuntu.com/c/desktop/8) and post your question there with a descriptive tag.
