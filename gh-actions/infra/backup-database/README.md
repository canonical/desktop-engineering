# Database backup action

This composite GitHub Action selects a healthy unit of a Juju application and
runs a database charm backup action on it. It requires an already authenticated
Juju session and reports the result in the GitHub job summary.

The [jaas-auth](../jaas-auth/action.yml) action can be used to install Juju and
authenticate to JAAS beforehand.

## Inputs

| Input         | Required | Default         | Description                                        |
| ------------- | -------- | --------------- | -------------------------------------------------- |
| `model`       | yes      |                 | Juju model name                                    |
| `model-owner` | no       |                 | Juju model owner, for models owned by another user |
| `application` | yes      |                 | Application whose units will be considered         |
| `action`      | no       | `create-backup` | Juju action name                                   |
| `parameters`  | no       | `{}`            | JSON object containing action parameters           |
| `unit-role`   | no       | `non-primary`   | `non-primary`, `primary`, or `any`                 |
| `timeout`     | no       | `6h`            | Duration passed to Juju's `--wait`, e.g. `30m`     |
| `dry-run`     | no       | `false`         | Skip backup creation but still list backups        |

Only `model` and `application` are strictly required. `model-owner` is only
needed when targeting a model owned by another user.

## Unit selection

Units with an unhealthy workload (`blocked` or `error`) or agent (`error` or
`lost`) status are excluded from selection. The unit with the workload status
message `Primary` is treated as the primary. With `non-primary`, the first
eligible non-primary unit is selected, falling back to the primary with a
degraded warning when no eligible replica remains. `any` skips role discovery.
Excluded units and degraded fallbacks are noted in the job summary.

For charms that support the `get-cluster-status` action (currently `mysql` and
`mysql-k8s`), unit selection uses the live cluster topology instead of the
possibly stale `juju status` primary marker. The action queries the leader
unit (falling back to the first eligible unit when the leader is unhealthy)
and selects from members whose status is `ONLINE` and whose `memberRole`
matches the requested role — `PRIMARY` for `primary`, `SECONDARY` for
`non-primary` (falling back to the `PRIMARY` member with a degraded warning),
or any `ONLINE` member for `any`. If the `get-cluster-status` action fails or
no member matches, the run fails rather than guessing from stale status.

## Usage

```yaml
steps:
  - uses: actions/checkout@v7
  - name: Authenticate to JAAS
    id: jaas-auth
    uses: canonical/desktop-engineering/gh-actions/infra/jaas-auth@main
    with:
      jaas-controller: ${{ vars.JUJU_CONTROLLER }}
      jaas-controller-host: ${{ vars.JUJU_CONTROLLER_HOST }}
      juju-client-id: ${{ secrets.JUJU_CLIENT_ID }}
      juju-client-secret: ${{ secrets.JUJU_CLIENT_SECRET }}
  - uses: canonical/desktop-engineering/gh-actions/infra/backup-database@main
    env:
      JUJU_DATA: ${{ steps.jaas-auth.outputs.juju-data }}
    with:
      model: example-model
      model-owner: ${{ vars.JUJU_MODEL_OWNER }}
      application: database
      dry-run: "true"
```

Invoke the action once per backup target. Run with `dry-run: "true"` first to
validate model access and unit selection before enabling backup creation.
