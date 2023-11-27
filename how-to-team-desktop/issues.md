# Issue Flow

Below is a sample flow for resolving issues, from an issue being opened to closing. The *Triage* flow is intended to be done as soon as someone has the bandwidth to apply it to a newly opened issue. Once done, the issue may rest at the end of the flow until it is work for the current Pulse, then, the *Resolve* flow can be applied.

![https://mermaid.live/edit#pako:eNp9VW1v2jAQ_iuWP0x0gq7QUmgmbUJllZhKh1g3aUv4YPABVoOd2U5HCvz3OXZCTBstH-K7x_fy3OXs7PBCUMABXsbi72JNpEaPw4gj86h0vpIkWeeCBCXiZwinbp05i_wZKMVWHLVan9CIAtdsmd2xbVjKiKAl29bbj4l8-sokCXMBEYVyxTP14ll7s1abJfgTpDGpcKfbrf2D0C7_3o9VazuZhpM0jtEU_qSgtMdiMnXBBkkixTPQPRpCEossHINcAXpXqDUedwB0ThZPJrsGSTSExZqT9-ssUMejwl1gC9_GQkHDvs-cAXD69jNpycgKwke7eBm-JcAbI6VSsCLQMxv1Cxfpaj3iS7FzYhRxZjS5IZoJ_vlwGsH6DFIt7skc4kaYi0hnCaA4B2ZnlXkV2bXiFyjTBTVMk5gtTK27o-Qnee31IPblB8nBsJCRx9FvYxXeS3rEXAvLUXOd-kDLXVP5PeNPyFTkY37Ha3PkFEdqCmY2aLpg8xh2vuJXd2rmUbyNiTkUyywsBTNUtsXvZ__3dv1xaH19XOiW9PxqS3obeEyyOXxE3Aww2ggJtuMn36Ly98CSFTLXRSK4yv3QFlGSmSrHzNTGV7U0lSa13N7E_qFAIkKpKhhVE1M5HbvoPBKlJZANsuO_R6VeyyMtNr1p8KDX7E4STSQTkmn2At5FcMTc0bFXX1jcgHlsU83MO864iTdgBptRcyHv8o0I6zVsIMKBEakhG-GIH4wdMWfve8YXONAyhSZOE2pmcmiqkGSDgyWJlUETwn8LcaLjYIe3OOj0Oue9dr970e13by573SbOcNDun3f7vZuri077-uL66qp7eWjiFxug3cRAmRZy7H4X9q9x-AdOngdB](https://mermaid.ink/img/pako:eNp9VW1v2jAQ_iuWP0x0gq7QUmgmbUJllZhKh1g3aUv4YPABVoOd2U5HCvz3OXZCTBstH-K7x_fy3OXs7PBCUMABXsbi72JNpEaPw4gj86h0vpIkWeeCBCXiZwinbp05i_wZKMVWHLVan9CIAtdsmd2xbVjKiKAl29bbj4l8-sokCXMBEYVyxTP14ll7s1abJfgTpDGpcKfbrf2D0C7_3o9VazuZhpM0jtEU_qSgtMdiMnXBBkkixTPQPRpCEossHINcAXpXqDUedwB0ThZPJrsGSTSExZqT9-ssUMejwl1gC9_GQkHDvs-cAXD69jNpycgKwke7eBm-JcAbI6VSsCLQMxv1Cxfpaj3iS7FzYhRxZjS5IZoJ_vlwGsH6DFIt7skc4kaYi0hnCaA4B2ZnlXkV2bXiFyjTBTVMk5gtTK27o-Qnee31IPblB8nBsJCRx9FvYxXeS3rEXAvLUXOd-kDLXVP5PeNPyFTkY37Ha3PkFEdqCmY2aLpg8xh2vuJXd2rmUbyNiTkUyywsBTNUtsXvZ__3dv1xaH19XOiW9PxqS3obeEyyOXxE3Aww2ggJtuMn36Ly98CSFTLXRSK4yv3QFlGSmSrHzNTGV7U0lSa13N7E_qFAIkKpKhhVE1M5HbvoPBKlJZANsuO_R6VeyyMtNr1p8KDX7E4STSQTkmn2At5FcMTc0bFXX1jcgHlsU83MO864iTdgBptRcyHv8o0I6zVsIMKBEakhG-GIH4wdMWfve8YXONAyhSZOE2pmcmiqkGSDgyWJlUETwn8LcaLjYIe3OOj0Oue9dr970e13by573SbOcNDun3f7vZuri077-uL66qp7eWjiFxug3cRAmRZy7H4X9q9x-AdOngdB?type=png)

**See [Labels](#labels) for labeling standards. Labeling doesn't only happen once, but is a continual process to document an issue's or PR's state.*

**Definitions**

| Word | Definition |
|------|------------|
| Duplicate | An open or closed issue already exists for the issue. |
| Reproducible | The issue can be encountered by someone other than the opener. |
| Stale | No activity has been received on an issue/PR within a set amount of time. Recommended time to be considered stale is 60 days, but can be variable depending on the project and issue. Generally should be automated. |

## Labels

*Edit repository labels at `https://github.com/<organization>/<repository>/labels`.*

Individual repositories should use these labels in addition to repository-specific labels to further classify issues and pull requests. For example, the [Steam Snap](https://github.com/canonical/steam-snap/labels) has labels to classify an issue further such as `game-specific`, `client-specific`, `hardware-specific`, etc that are labels exclusive to the Snap. Many repositories may not need additional labels other than the ones defined below.

### Types

Generally an issue or PR should have exactly one of the following labels indiciating the type of the issue or PR. These may be automatically applied by using [issues templates](#templates) and *usually are never changed or removed once added*.

| Label | Use Case |
|-------|----------|
| `type/bug` | Issues that are related to a problem or unexpected behavior. |
| `type/documentation` | Issues or PRs relating to documentation or wiki pages. |
| `type/enhancement` | Issues or PRs relating to new feature requests. |
| `type/question` | Issues requesting information or to have a discussion. |

### Triage States

Labels to be applied while triaging an issue, indicating the result of triage. Usually these states lead to the issue or PR being closed once applied.

| Label | Use Case |
|-------|----------|
| `triage/duplicate` | Issues or PRs that already have an existing issue or PR. |
| `triage/invalid` | Issues or PRs that are not relevant. |
| `triage/not-reproducible` | Issues that cannot be encountered by someone else. |
| `triage/stale` | Issues or PRs that have not had activity in a set amount of time, usually ~60 days. |
| `triage/upstream` | Issues that are actually an upstream issue, not an issue with this repository. |

### Priority

Labels to be applied indicating the priority of an issue or PR.

| Label | Use Case |
|-------|----------|
| `priority/high` | Issues or PRs with high priority. |
| `priority/medium` | Issues or PRs with medium priority. |
| `priority/low` | Issues or PRs with low priority. |

### Further Labels

Labels that may be added or removed at any point to an issue or PR that further documents its state.

| Label | Use Case |
|-------|----------|
| `good-first-issue` | Issues that are good for first-time contributors. These should be small, well defined, well documented, and low priority fixes or features with a clear solution. In addition, team members should be willing to guide the contributor through the process. `help-wanted` should always be used alongside `good-first-issue`. |
| `help-wanted` | Issues or PRs that may need additional help from others. These should be clearly defined, have assisting documentation, and have a low priority. |
| `jira` | Used to open a corresponding Jira card for the issue. |
| `needs-information` | Issues that need more information before further work or triage is possible. |
| `needs-scoping` | Issues that needs to be scoped/investigated before committing to solving. Usually used alongside the `type/enhancement` label. |
| `needs-triage` | Issues that still need to be triaged. Could be automatically added alongside `type/bug` for bug [templates](#templates). |
| `wontfix` | Issues or PRs that will no longer be considered. The issue or PR should generally be closed after adding this label. |

### Label Colors

You may use whatever colors you'd like, but below are some recommendations to follow.

| Color | Use Case | Example Labels |
|-------|----------|----------|
| Reds | Problems, errors, or to indicate urgency. | `type/bug`, `priority/high` |
| Yellows and oranges | Waiting states or medium urgency. | `priority/medium`, `needs-scoping`, `needs-triage`, `help-wanted` |
| Greens | Success states or low urgency. | `priority/low`, `good-first-issue` |
| Blues | Features or additions. | `type/enchancement`, `type/documentation` |
| Grays | Triage or close states. | `triage/duplicate`, `triage/invalid`, `triage/not-reproducible`, `triage/stale`, `wontfix` |

## Templates

Most repositories should have [issue templates](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/about-issue-and-pull-request-templates) to get better information on initial open and reduce back and forth with the opener. Issue templates also allow the issue to be automatically labeled when its open; this is useful for templates that differentiate bugs, feature requests, etc.

Issue templates can take the form of simple [Markdown files](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/configuring-issue-templates-for-your-repository#creating-issue-templates) or more advanced [YAML files](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/configuring-issue-templates-for-your-repository#creating-issue-forms). Markdown issue templates will simply insert the content of the file into the issue body when an issue is opened for that type. YAML form templates instead create interactive forms, with elements like text boxes, drop-downs, checkboxes, etc.

## Further Resources

- [Bug Triage, Ubuntu Wiki](https://wiki.ubuntu.com/Bugs/Triage)
- [Bug Triage Flowcharts, Ubuntu Wiki](https://wiki.ubuntu.com/Bugs/Triage/Charts)
