#!/usr/bin/env python3

"""Back up database cluster credentials to Vault."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from backup_helpers import (
    CommandCapture,
    CommandRunner,
    juju_operations,
    juju_run,
    run_command,
    set_result_output,
)
from constants import SUMMARY_DRY_RUN, SUMMARY_FAILURE, SUMMARY_SUCCESS

logger = logging.getLogger(__name__)

VAULT_CREDENTIAL_OUTPUT_PREFIX = "CURRENT_"


class CredentialBackupError(RuntimeError):
    """Raised when cluster credentials cannot be retrieved or stored."""


@dataclass(frozen=True)
class CredentialTarget:
    """Configuration for one database credential backup target."""

    model: str
    application: str
    model_owner: str = ""
    timeout: str = "6h"
    usernames: tuple[str, ...] = ()
    secret_path: str = ""
    vault_credentials: Mapping[str, str] = field(default_factory=dict)
    vault_secret_exists: bool = False

    @property
    def qualified_model(self) -> str:
        """Return the owner-qualified model name expected by Juju."""

        if not self.model_owner:
            return self.model
        return f"{self.model_owner}/{self.model}"

    @property
    def target_name(self) -> str:
        """Return the target name used in logs and summaries."""

        return f"{self.model}/{self.application}"


def target_from_action_inputs(values: Mapping[str, str]) -> CredentialTarget:
    """Build a normalized credential target from action environment values."""

    usernames = tuple(
        dict.fromkeys(
            username.strip()
            for username in values.get("CREDENTIAL_USERNAMES", "").split(",")
            if username.strip()
        )
    )
    vault_outputs = json.loads(values.get("VAULT_CREDENTIAL_OUTPUTS_JSON", "{}"))
    if not isinstance(vault_outputs, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in vault_outputs.items()
    ):
        raise TypeError("Vault credential outputs must be a JSON object of strings")

    output_keys = [_vault_action_output_key(username) for username in usernames]
    if len(set(output_keys)) != len(output_keys):
        raise ValueError("credential usernames produce duplicate Vault Action outputs")
    vault_credentials = {
        username: vault_outputs[output_key]
        for username, output_key in zip(usernames, output_keys)
        if output_key in vault_outputs
    }

    application = values.get("APPLICATION", "").strip()
    if not application:
        raise ValueError("application is required")
    model = values.get("MODEL", "").strip()
    if not model:
        raise ValueError("model is required")
    secret_path = values.get("CREDENTIALS_SECRET_PATH", "").strip()
    if not secret_path:
        raise ValueError("credentials secret path is required")
    model_owner = values.get("MODEL_OWNER", "").strip()
    return CredentialTarget(
        model=model,
        application=application,
        model_owner=model_owner,
        timeout=values.get("TIMEOUT", "6h"),
        usernames=usernames,
        secret_path=secret_path,
        vault_credentials=vault_credentials,
        vault_secret_exists=bool(vault_credentials),
    )


def _vault_action_output_key(username: str) -> str:
    """Return the output name produced by Vault Action for one username.

    Vault Action normalizes secret keys into valid output names: dots become
    double underscores, dashes are dropped, and any remaining non-alphanumeric
    characters are stripped. Mirror that here so we can match each username
    against the keys in toJSON(steps.cluster-credentials.outputs).
    """

    value = f"{VAULT_CREDENTIAL_OUTPUT_PREFIX}{username}".replace(".", "__")
    value = value.replace("-", "")
    return "".join(
        character for character in value if character == "_" or character.isalnum()
    )


def run_credential_backup(
    target: CredentialTarget,
    *,
    dry_run: bool,
    output_path: Path | None,
    command_runner: CommandRunner | None = None,
    temporary_root: Path | None = None,
) -> int:
    """Retrieve cluster credentials and update Vault only when needed."""

    if not target.usernames:
        logger.info("Cluster credential backup is not configured")
        return 0

    mode = "dry run" if dry_run else "live backup"
    logger.info("Starting credential %s for %s", mode, target.target_name)
    try:
        with tempfile.TemporaryDirectory(dir=temporary_root) as temporary_directory:
            changed = _backup_cluster_credentials(
                target,
                dry_run=dry_run,
                runner=command_runner or run_command,
                temporary_directory=Path(temporary_directory),
            )
    except CredentialBackupError as error:
        logger.error(
            "Unable to back up cluster credentials for %s: %s",
            target.target_name,
            error,
        )
        set_result_output(
            output_path,
            operation="credential backup",
            target=target.target_name,
            result=SUMMARY_FAILURE,
            notes="Credential retrieval or storage failed",
        )
        return 1

    set_result_output(
        output_path,
        operation="credential backup",
        target=target.target_name,
        result=SUMMARY_DRY_RUN if dry_run else SUMMARY_SUCCESS,
        notes=_summary_note(dry_run=dry_run, credentials_changed=changed),
    )
    logger.info("Completed credential %s for %s", mode, target.target_name)
    return 0


def _backup_cluster_credentials(
    target: CredentialTarget,
    *,
    dry_run: bool,
    runner: CommandRunner,
    temporary_directory: Path,
) -> bool:
    """Retrieve configured credentials and update Vault only when needed."""

    credential_count = len(target.usernames)
    logger.info("Validating %d configured cluster credential(s)", credential_count)
    credentials: dict[str, str] = {}
    for index, username in enumerate(target.usernames):
        logger.info(
            "Retrieving cluster credential for %s (%d of %d)",
            username,
            index + 1,
            credential_count,
        )
        capture = CommandCapture.create(temporary_directory, f"credential-{index}")
        succeeded = juju_run(
            runner,
            capture,
            target.qualified_model,
            f"{target.application}/leader",
            "get-password",
            f"username={username}",
            f"--wait={target.timeout}",
        )
        if not succeeded:
            raise CredentialBackupError(
                f"get-password failed for {username}; command output was withheld"
            )
        password = _password_from_juju_output(
            capture.stdout, expected_username=username
        )
        _mask_secret(password)
        credentials[username] = password

    logger.info("Configured cluster credentials were retrieved successfully")
    logger.info("Comparing cluster credentials with the values read from Vault")
    if all(
        target.vault_credentials.get(key) == value for key, value in credentials.items()
    ):
        logger.info("Cluster credentials are already current; skipping the Vault write")
        return False

    if dry_run:
        logger.info("Dry run: cluster credentials differ; skipping the Vault write")
        return False

    logger.info("Cluster credentials changed; writing the updated values to Vault")
    vault_input = temporary_directory / "vault-credentials-input.json"
    vault_input.write_text(json.dumps(credentials))
    vault_input.chmod(0o600)
    capture = CommandCapture.create(temporary_directory, "vault-write")
    command = [
        "vault",
        "kv",
        "patch" if target.vault_secret_exists else "put",
        *(["-method=rw"] if target.vault_secret_exists else []),
        "-mount=secret",
        target.secret_path,
        f"@{vault_input}",
    ]
    if capture.run(runner, command) != 0:
        reason = capture.stderr.read_text(errors="replace").strip()
        raise CredentialBackupError(
            f"Vault write failed: {reason or 'Vault exited with no error output'}"
        )
    logger.info("Cluster credentials were updated in Vault successfully")
    return True


def _mask_secret(value: str) -> None:
    """Register a secret with the GitHub Actions log masker."""

    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    escaped = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::add-mask::{escaped}", flush=True)


def _password_from_juju_output(output_path: Path, *, expected_username: str) -> str:
    """Extract one non-empty password from a completed ``get-password`` run."""

    try:
        operations = juju_operations(output_path)
        if len(operations) != 1:
            raise ValueError
        operation = operations[0]
        results = operation.get("results")
        if (
            operation.get("status") != "completed"
            or not isinstance(results, dict)
            or results.get("return-code") != 0
            or results.get("username") != expected_username
            or not isinstance(results.get("password"), str)
            or not results["password"]
        ):
            raise ValueError
        return results["password"]
    except (json.JSONDecodeError, OSError, ValueError) as error:
        raise CredentialBackupError(
            f"get-password returned an invalid result for {expected_username}"
        ) from error


def _summary_note(*, dry_run: bool, credentials_changed: bool) -> str:
    """Describe credential handling for the summary."""

    if dry_run:
        return "Cluster credential retrieval validated; Vault write skipped"
    if credentials_changed:
        return "Cluster credentials updated in Vault"
    return "Cluster credentials already current in Vault"


def main() -> int:
    """Validate action environment inputs and run credential backup."""

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
    return run_credential_backup(
        target,
        dry_run=dry_run_value == "true",
        output_path=Path(output_value) if output_value else None,
        temporary_root=(
            Path(os.environ["RUNNER_TEMP"]) if os.environ.get("RUNNER_TEMP") else None
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
