#!/usr/bin/env python3

"""Select a healthy Juju unit and run a database backup."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backup_helpers import (
    CommandCapture,
    CommandRunner,
    join_notes,
    juju_operations,
    juju_run,
    juju_run_succeeded,
    parameter_value,
    read_json_object,
    run_command,
    set_result_output,
)

logger = logging.getLogger(__name__)

# Charms whose Juju status primary marker lags behind reality; for these, the
# get-cluster-status action provides the authoritative member roles.
_CLUSTER_STATUS_ACTION = "get-cluster-status"
_CLUSTER_STATUS_CHARMS = frozenset({"mysql", "mysql-k8s"})
_ONLINE_MEMBER = "ONLINE"

# Cluster states in which get-cluster-status reports the topology as usable.
_HEALTHY_CLUSTER_STATES = frozenset({"OK", "OK_PARTIAL"})

# Translation from user-facing roles to get-cluster-status memberRole names.
_MEMBER_ROLES = {"non-primary": "SECONDARY", "primary": "PRIMARY"}

_UNIT_PATTERN = re.compile(r"/(?P<number>[0-9]+)$")

class SelectionError(ValueError):
    """Raised when no unit satisfies the requested selection policy."""


@dataclass(frozen=True)
class BackupTarget:
    """Configuration for one database backup target."""

    application: str
    model: str
    model_owner: str = ""
    action: str = "create-backup"
    parameters: Mapping[str, Any] = field(default_factory=dict)
    unit_role: str = "non-primary"
    timeout: str = "6h"

    @property
    def qualified_model(self) -> str:
        """Return the owner-qualified model name expected by Juju."""

        if not self.model_owner:
            return self.model
        return f"{self.model_owner}/{self.model}"


@dataclass(frozen=True)
class Exclusion:
    """A Juju unit excluded from selection and the reasons why."""

    unit: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Selection:
    """Selected Juju unit and the health information behind that choice."""

    unit: str
    requested_role: str
    selected_role: str
    warning: str | None
    workload: str
    agent: str
    excluded: tuple[Exclusion, ...]


@dataclass(frozen=True)
class _ClusterMember:
    """One cluster member's topology role and reachability status."""

    role: str
    status: str


class _ClusterStatusSelector(_Selector):
    """Select a unit using get-cluster-status topology roles and member health."""

    def select(
        self, members: Mapping[str, _ClusterMember], unit_role: str
    ) -> Selection:
        """Select an online eligible unit matching the requested member role."""

        eligible = self.eligible()
        for unit in self.units:
            if unit.name not in members:
                unit.reasons.append("missing from cluster topology")
        online = {
            unit.name: member
            for unit in eligible
            if (member := members.get(unit.name)) is not None
            and member.status == _ONLINE_MEMBER
        }
        if not online:
            raise SelectionError(
                f"application {self.application} has no online eligible cluster members"
            )

        warning = None
        if unit_role == "ANY":
            selected_name = min(online, key=_unit_number)
        else:
            matches = [
                name for name, member in online.items() if member.role == unit_role
            ]
            # In single member scenarios, try to fall back to the primary.
            if not matches and unit_role == "SECONDARY" and len(members) == 1:
                matches = [
                    name for name, member in online.items() if member.role == "PRIMARY"
                ]
                if matches:
                    warning = "no online secondary unit; selected the primary"
            if not matches:
                raise SelectionError(
                    f"application {self.application} has no online eligible"
                    f" {unit_role.lower()} member"
                )
            selected_name = min(matches, key=_unit_number)
        selected_member = online[selected_name]

        return Selection(
            unit=selected_name,
            requested_role=unit_role,
            selected_role=(
                "primary" if selected_member.role == "PRIMARY" else "secondary"
            ),
            warning=warning,
            workload="online",
            agent="online",
            excluded=self.exclusions(),
        )


def _parse_cluster_members(
    document: Mapping[str, Any], application: str
) -> dict[str, _ClusterMember]:
    """Map topology member names to units, capturing memberRole and status."""

    try:
        replica_set = document["defaultReplicaSet"]
        cluster_status = replica_set["status"]
        if cluster_status not in _HEALTHY_CLUSTER_STATES:
            raise SelectionError(f"cluster is not in a healthy state: {cluster_status}")
        topology = replica_set["topology"]
        if not topology:
            raise KeyError("topology")
        prefix = f"{application.removeprefix('cs:')}-"
        members: dict[str, _ClusterMember] = {}
        for name, member in topology.items():
            if not name.startswith(prefix):
                raise KeyError(name)
            number = name.removeprefix(prefix)
            if not number.isdigit():
                raise KeyError(name)
            members[f"{application}/{number}"] = _ClusterMember(
                role=member["memberRole"],
                status=member["status"],
            )
        return members
    except (KeyError, TypeError) as error:
        raise SelectionError(f"malformed cluster status document: {error}") from error


# ---------------------------------------------------------------------------
# Backup orchestration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RunContext:
    """Resources and reporting details shared by one target run."""

    target: BackupTarget
    dry_run: bool
    output_path: Path | None
    runner: CommandRunner
    temporary_directory: Path

    @property
    def target_name(self) -> str:
        """Return the target name used in logs and summaries."""

        return f"{self.target.model}/{self.target.application}"

    def capture(self, name: str) -> CommandCapture:
        """Create command capture paths in this run's temporary directory."""

        return CommandCapture.create(self.temporary_directory, name)

    def record_result(self, *, unit: str | None, result: str, notes: str) -> None:
        """Record this target's outcome for the final summary step."""

        set_result_output(
            self.output_path,
            operation="backup",
            target=self.target_name,
            unit=unit,
            result=result,
            notes=notes,
        )

    def juju_run(
        self, name: str, unit: str, action: str, *arguments: str
    ) -> tuple[CommandCapture, bool]:
        """Run a Juju action and return its capture plus envelope success."""

        capture = self.capture(name)
        succeeded = juju_run(
            self.runner,
            capture,
            self.target.qualified_model,
            unit,
            action,
            *arguments,
        )
        return capture, succeeded


UNIT_PATTERN = re.compile(r"/(?P<number>[0-9]+)$")
SUMMARY_FAILURE = "❌ Failure"
SUMMARY_SUCCESS = "✅ Success"
SUMMARY_DEGRADED_SUCCESS = "⚠️ Success (degraded)"
SUMMARY_DRY_RUN = "⏭️ Dry run"
SUMMARY_DEGRADED_DRY_RUN = "⏭️ Dry run (degraded)"

# Charms whose Juju status primary marker lags behind reality; for these, the
# get-cluster-status action provides the authoritative member roles.
CLUSTER_STATUS_ACTION = "get-cluster-status"
CLUSTER_STATUS_CHARMS = frozenset({"mysql", "mysql-k8s"})
ONLINE_MEMBER = "ONLINE"


def target_from_action_inputs(values: Mapping[str, str]) -> BackupTarget:
    """Build a normalized backup target from action environment values."""

    parameters = json.loads(values.get("PARAMETERS_JSON", "{}"))
    if not isinstance(parameters, dict):
        raise TypeError("parameters must be a JSON object")
    application = values.get("APPLICATION", "").strip()
    if not application:
        raise ValueError("application is required")
    model = values.get("MODEL", "").strip()
    if not model:
        raise ValueError("model is required")
    model_owner = values.get("MODEL_OWNER", "").strip()
    return BackupTarget(
        application=application,
        model=model,
        model_owner=model_owner,
        action=values["ACTION"],
        parameters=parameters,
        unit_role=values["UNIT_ROLE"],
        timeout=values["TIMEOUT"],
    )


def _model_arguments(target: BackupTarget) -> list[str]:
    """Return the --model arguments for Juju commands."""

    return ["--model", target.qualified_model]


def select_backup_unit(
    status: Mapping[str, Any], application: str, unit_role: str
) -> Selection:
    """Select an eligible application unit using workload health and role."""

    if unit_role not in {"non-primary", "primary", "any"}:
        raise SelectionError(f"invalid unit role: {unit_role}")
    applications = status.get("applications")
    if not isinstance(applications, dict):
        raise SelectionError("status does not contain an applications object")
    application_status = applications.get(application)
    if not isinstance(application_status, dict):
        raise SelectionError(f"application {application} is not present in status")
    units = application_status.get("units")
    if not isinstance(units, dict):
        raise SelectionError(
            f"application {application} does not contain a units object"
        )
    if not units:
        raise SelectionError(f"application {application} has no units")

    parsed_units = sorted(
        (_parse_unit(name, value) for name, value in units.items()),
        key=lambda unit: _unit_number(unit["unit"]),
    )
    eligible = [unit for unit in parsed_units if not unit["reasons"]]
    if not eligible:
        raise SelectionError(f"application {application} has no eligible units")

    primaries = [unit for unit in parsed_units if unit["primary"]]
    warning = None
    if unit_role == "any":
        selected = eligible[0]
    else:
        if len(primaries) != 1:
            raise SelectionError(
                f"application {application} must have exactly one unit with status message Primary"
            )
        eligible_primaries = [unit for unit in eligible if unit["primary"]]
        eligible_replicas = [unit for unit in eligible if not unit["primary"]]
        if unit_role == "primary":
            if not eligible_primaries:
                raise SelectionError("the primary unit is not eligible")
            selected = eligible_primaries[0]
        elif eligible_replicas:
            selected = eligible_replicas[0]
        else:
            selected = eligible_primaries[0]
            warning = "no eligible non-primary unit; selected the primary"

    excluded = tuple(
        Exclusion(unit["unit"], tuple(unit["reasons"]))
        for unit in parsed_units
        if unit["reasons"]
    )
    return Selection(
        unit=selected["unit"],
        requested_role=unit_role,
        selected_role="primary" if selected["primary"] else "non-primary",
        warning=warning,
        workload=selected["workload"],
        agent=selected["agent"],
        excluded=excluded,
    )


def _parse_unit(name: Any, value: Any) -> dict[str, Any]:
    """Normalize one Juju unit and record health-based exclusion reasons."""

    if not isinstance(name, str) or not UNIT_PATTERN.search(name):
        raise SelectionError(f"invalid unit name: {name}")
    if not isinstance(value, dict):
        raise SelectionError(f"unit {name} has malformed status")
    workload_status = value.get("workload-status")
    agent_status = value.get("juju-status")
    if not isinstance(workload_status, dict) or not isinstance(agent_status, dict):
        raise SelectionError(f"unit {name} has malformed workload or agent status")
    workload = workload_status.get("current")
    agent = agent_status.get("current")
    message = workload_status.get("message", "")
    if (
        not isinstance(workload, str)
        or not isinstance(agent, str)
        or not isinstance(message, str)
    ):
        raise SelectionError(f"unit {name} has malformed workload or agent status")

    reasons = []
    if workload in {"blocked", "error"}:
        reasons.append(f"workload is {workload}")
    if agent in {"error", "lost"}:
        reasons.append(f"agent is {agent}")
    return {
        "unit": name,
        "workload": workload,
        "agent": agent,
        "primary": message == "Primary",
        "reasons": reasons,
    }


def _unit_number(name: str) -> int:
    """Return the integer suffix used to order Juju unit names."""

    match = UNIT_PATTERN.search(name)
    if match is None:
        raise SelectionError(f"invalid unit name: {name}")
    return int(match.group("number"))


def run_target(
    target: BackupTarget,
    *,
    dry_run: bool,
    output_path: Path | None,
    command_runner: CommandRunner | None = None,
    temporary_root: Path | None = None,
) -> int:
    """Run unit selection, backup creation, and backup verification."""

    mode = "dry run" if dry_run else "live backup"
    logger.info("Starting %s for %s/%s", mode, target.model, target.application)
    with tempfile.TemporaryDirectory(dir=temporary_root) as temporary_directory:
        context = RunContext(
            target=target,
            dry_run=dry_run,
            output_path=output_path,
            runner=command_runner or run_command,
            temporary_directory=Path(temporary_directory),
        )
        selection = _select_target_unit(context)
        if selection is None:
            return 1
        logger.info(
            "Selected %s (%s); workload=%s, agent=%s",
            selection.unit,
            selection.selected_role,
            selection.workload,
            selection.agent,
        )
        if selection.warning:
            logger.warning(
                "Unit selection is degraded; no eligible requested-role unit found"
            )
        if selection.excluded:
            logger.info(
                "Excluded %d unhealthy unit(s) from selection", len(selection.excluded)
            )

        notes = _selection_notes(selection)
        if dry_run:
            logger.info("Dry run: skipping the backup action")
        elif not _run_backup_action(context, selection, notes):
            return 1
        if not _list_backups(context, selection, notes):
            return 1

        context.record_result(
            unit=selection.unit,
            result=_success_result(selection, dry_run=dry_run),
            notes=join_notes(
                notes,
                "backup action not run" if dry_run and notes else None,
                "Selection validated; backup action not run"
                if dry_run and not notes
                else None,
            ),
        )
        logger.info("Completed %s for %s", mode, context.target_name)
        return 0


def requires_cluster_status(status: Mapping[str, Any], application: str) -> bool:
    """Return whether the application runs a charm with cluster-status support."""

    charm = status.get("applications", {}).get(application, {}).get("charm")
    return isinstance(charm, str) and charm.split(":")[-1] in CLUSTER_STATUS_CHARMS


def parse_cluster_members(
    document: Mapping[str, Any], application: str
) -> dict[str, dict[str, str]]:
    """Map topology member names to units, capturing memberRole and status."""

    try:
        topology = document["defaultReplicaSet"]["topology"]
        if not topology:
            raise KeyError("topology")
        prefix = f"{application.removeprefix('cs:')}-"
        members: dict[str, dict[str, str]] = {}
        for name, member in topology.items():
            if not name.startswith(prefix):
                raise KeyError(name)
            number = name.removeprefix(prefix)
            if not number.isdigit():
                raise KeyError(name)
            members[f"{application}/{number}"] = {
                "role": member["memberRole"],
                "status": member["status"],
            }
        return members
    except (KeyError, TypeError) as error:
        raise SelectionError(f"malformed cluster status document: {error}") from error


def select_cluster_status_unit(
    parsed_units: Sequence[dict[str, Any]],
    members: Mapping[str, Mapping[str, str]],
    application: str,
    unit_role: str,
) -> Selection:
    """Select a unit using get-cluster-status topology roles and member health."""

    eligible = [unit for unit in parsed_units if not unit["reasons"]]
    if not eligible:
        raise SelectionError(f"application {application} has no eligible units")
    for unit in parsed_units:
        if unit["unit"] not in members:
            unit["reasons"].append("missing from cluster topology")
    online = {
        unit["unit"]: member
        for unit in eligible
        if (member := members.get(unit["unit"])) is not None
        and member["status"] == ONLINE_MEMBER
    }
    if not online:
        raise SelectionError(
            f"application {application} has no online eligible cluster members"
        )

    warning = None
    if unit_role == "ANY":
        selected_name = min(online, key=_unit_number)
    else:
        matches = [
            name for name, member in online.items() if member["role"] == unit_role
        ]
        if not matches and unit_role == "SECONDARY":
            matches = [
                name for name, member in online.items() if member["role"] == "PRIMARY"
            ]
            if matches:
                warning = "no online secondary unit; selected the primary"
        if not matches:
            raise SelectionError(
                f"application {application} has no online eligible {unit_role.lower()} member"
            )
        selected_name = min(matches, key=_unit_number)
    selected_member = online[selected_name]

    excluded = tuple(
        Exclusion(unit["unit"], tuple(unit["reasons"]))
        for unit in parsed_units
        if unit["reasons"]
    )
    return Selection(
        unit=selected_name,
        requested_role=unit_role,
        selected_role="primary" if selected_member["role"] == "PRIMARY" else "secondary",
        warning=warning,
        workload="online",
        agent="online",
        excluded=excluded,
    )


def _select_target_unit(context: RunContext) -> Selection | None:
    """Read Juju status and select a unit, reporting failures to the summary."""

    target = context.target
    logger.info("Reading Juju status for %s", context.target_name)
    capture = context.capture("status")
    command = [
        "juju",
        "status",
        *_model_arguments(target),
        target.application,
        "--format=json",
    ]
    if capture.run(context.runner, command) != 0:
        logger.error(
            "Unable to read Juju status for %s; command output was withheld",
            context.target_name,
        )
        context.record_result(
            unit=None, result=SUMMARY_FAILURE, notes="Unable to read Juju status"
        )
        return None
    try:
        status = read_json_object(capture.stdout)
        if requires_cluster_status(status, target.application):
            return _select_cluster_status_unit(context, status)
        return select_backup_unit(status, target.application, target.unit_role)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as error:
        logger.error(
            "Unable to select a backup unit for %s: %s", context.target_name, error
        )
        context.record_result(
            unit=None,
            result=SUMMARY_FAILURE,
            notes=f"Unable to select a backup unit: {error}",
        )
        return None


def _select_cluster_status_unit(
    context: RunContext, status: Mapping[str, Any]
) -> Selection | None:
    """Select a unit using the charm's get-cluster-status action output."""

    target = context.target
    # Translate the user-facing role to memberRole naming (PRIMARY/SECONDARY)
    unit_role = {"non-primary": "SECONDARY", "primary": "PRIMARY"}.get(
        target.unit_role, "ANY"
    )
    applications = status["applications"]
    application_status = applications[target.application]
    units = application_status.get("units")
    if not isinstance(units, dict) or not units:
        raise SelectionError(
            f"application {target.application} has no units in status"
        )
    parsed_units = sorted(
        (_parse_unit(name, value) for name, value in units.items()),
        key=lambda unit: _unit_number(unit["unit"]),
    )
    eligible = [unit for unit in parsed_units if not unit["reasons"]]
    if not eligible:
        raise SelectionError(f"application {target.application} has no eligible units")
    query_unit = eligible[0]

    logger.info("Reading cluster status from %s", query_unit["unit"])
    capture, succeeded = context.juju_run(
        "cluster-status", query_unit["unit"], CLUSTER_STATUS_ACTION
    )
    if not succeeded:
        raise SelectionError(
            f"{CLUSTER_STATUS_ACTION} failed on {query_unit['unit']}"
        )
    operations = juju_operations(capture.stdout)
    cluster_status = operations[0].get("results", {}).get("status")
    if not isinstance(cluster_status, str):
        raise SelectionError(
            f"{CLUSTER_STATUS_ACTION} did not return a status document"
        )
    document = json.loads(cluster_status)
    if not isinstance(document, dict):
        raise SelectionError("cluster status document is not an object")
    members = parse_cluster_members(document, target.application)
    return select_cluster_status_unit(
        parsed_units, members, target.application, unit_role
    )


def _run_backup_action(context: RunContext, selection: Selection, notes: str) -> bool:
    """Run the configured backup action, withholding its captured stdout."""

    target = context.target
    logger.info("Running the configured backup action on %s", selection.unit)
    _, succeeded = context.juju_run(
        "action",
        selection.unit,
        target.action,
        f"--wait={target.timeout}",
        *(
            f"{name}={parameter_value(value)}"
            for name, value in target.parameters.items()
        ),
    )
    if succeeded:
        logger.info("Backup action completed successfully on %s", selection.unit)
        return True
    logger.error(
        "Backup action failed for %s on %s; action output was withheld",
        context.target_name,
        selection.unit,
    )
    context.record_result(
        unit=selection.unit,
        result=SUMMARY_FAILURE,
        notes=join_notes(notes, "Backup action failed"),
    )
    return False


def _list_backups(context: RunContext, selection: Selection, notes: str) -> bool:
    """List backups, forwarding its output and reporting verification failures."""

    target = context.target
    logger.info("Listing backups on %s; command output follows", selection.unit)
    capture, succeeded = context.juju_run(
        "list-backups", selection.unit, "list-backups", f"--wait={target.timeout}"
    )
    if succeeded:
        capture.print()
        logger.info("Backup listing completed successfully on %s", selection.unit)
        return True
    logger.error(
        "Unable to list backups for %s on %s; command output was withheld",
        context.target_name,
        selection.unit,
    )
    failure = (
        "list-backups failed during dry run"
        if context.dry_run
        else "Backup succeeded but list-backups failed"
    )
    context.record_result(
        unit=selection.unit,
        result=SUMMARY_FAILURE,
        notes=join_notes(notes, failure),
    )
    return False


def _selection_notes(selection: Selection) -> str:
    """Describe degraded selection and every health-based unit exclusion."""

    notes = [selection.warning] if selection.warning else []
    notes.extend(
        f"excluded {exclusion.unit}: {', '.join(exclusion.reasons)}"
        for exclusion in selection.excluded
    )
    return "; ".join(notes)


def _success_result(selection: Selection, *, dry_run: bool) -> str:
    """Choose the summary result for dry-run and degraded-success states."""

    degraded = selection.warning is not None
    if dry_run:
        return SUMMARY_DEGRADED_DRY_RUN if degraded else SUMMARY_DRY_RUN
    return SUMMARY_DEGRADED_SUCCESS if degraded else SUMMARY_SUCCESS


def main() -> int:
    """Validate action environment inputs and run the database backup."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    dry_run_value = os.environ.get("DRY_RUN", "false").lower()
    if dry_run_value not in {"true", "false"}:
        logger.error("DRY_RUN must be true or false")
        return 2
    try:
        target = target_from_action_inputs(os.environ)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        logger.error("Invalid action inputs: %s", error)
        return 2
    output_value = os.environ.get("GITHUB_OUTPUT")
    return run_target(
        target,
        dry_run=dry_run_value == "true",
        output_path=Path(output_value) if output_value else None,
        temporary_root=(
            Path(os.environ["RUNNER_TEMP"]) if os.environ.get("RUNNER_TEMP") else None
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
