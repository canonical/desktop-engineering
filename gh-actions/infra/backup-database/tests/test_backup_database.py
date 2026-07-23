from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

ACTION_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(ACTION_DIR))


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, ACTION_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


backup_helpers = load_module("backup_helpers")
backup = load_module("backup")
TEST_MODEL_OWNER = "test-owner"
DEFAULT_ACTION_INPUTS = {
    "ACTION": "create-backup",
    "PARAMETERS_JSON": "{}",
    "UNIT_ROLE": "non-primary",
    "TIMEOUT": "6h",
}


class FakeRunner:
    def __init__(
        self,
        fixture: dict[str, Any],
        fail_model: str | None = None,
        fail_status: bool = False,
        failed_action: str | None = None,
    ):
        self.fixture = fixture
        self.fail_model = fail_model
        self.fail_status = fail_status
        self.failed_action = failed_action
        self.commands: list[list[str]] = []

    @staticmethod
    def _model(command: list[str]) -> str | None:
        if "--model" not in command:
            return None
        return command[command.index("--model") + 1]

    @staticmethod
    def _unit(command: list[str]) -> str:
        if "--model" in command:
            return command[command.index("--model") + 2]
        return command[2]

    @staticmethod
    def _action(command: list[str]) -> str:
        if "--model" in command:
            return command[command.index("--model") + 3]
        return command[3]

    def __call__(self, command: list[str], stdout: Path, stderr: Path) -> int:
        self.commands.append(list(command))
        stdout.touch()
        stderr.touch()
        if command[1] == "status":
            if self.fail_status:
                stderr.write_text("simulated status failure")
                return 1
            stdout.write_text(json.dumps(self.fixture))
            return 0
        if self.fail_model and self._model(command) == self.fail_model:
            stderr.write_text("simulated failure")
            return 1
        action = self._action(command)
        unit = self._unit(command)
        status = "failed" if action == self.failed_action else "completed"
        if action == "list-backups":
            stdout.write_text(
                json.dumps(
                    {
                        unit: {
                            "message": "backup-2026-07-22",
                            "status": status,
                        }
                    }
                )
            )
            stderr.write_text("list warning\n")
            return 0
        stdout.write_text(json.dumps({unit: {"status": status}}))
        return 0


def read_records(path: Path) -> list[dict]:
    name, value = path.read_text().strip().split("=", maxsplit=1)
    assert name == "result"
    return [json.loads(value)]


class DatabaseBackupTests(unittest.TestCase):
    fixtures = Path(__file__).parent / "fixtures"

    def fixture(self, name: str) -> dict[str, Any]:
        return json.loads((self.fixtures / name).read_text())

    def test_selects_first_healthy_replica(self):
        selection = backup.select_backup_unit(
            self.fixture("healthy-three.json"), "database", "non-primary"
        )
        self.assertEqual(selection.unit, "database/1")
        self.assertFalse(selection.degraded)

    def test_selects_primary_when_requested(self):
        selection = backup.select_backup_unit(
            self.fixture("healthy-three.json"), "database", "primary"
        )
        self.assertEqual(selection.unit, "database/0")

    def test_any_selects_first_healthy_unit(self):
        selection = backup.select_backup_unit(
            self.fixture("healthy-three.json"), "database", "any"
        )
        self.assertEqual(selection.unit, "database/0")

    def test_falls_back_to_primary_and_records_exclusions(self):
        selection = backup.select_backup_unit(
            self.fixture("unhealthy-replicas.json"), "database", "non-primary"
        )
        self.assertEqual(selection.unit, "database/0")
        self.assertTrue(selection.degraded)
        self.assertEqual(len(selection.excluded), 2)

    def test_excludes_lost_agent(self):
        selection = backup.select_backup_unit(
            self.fixture("agent-unhealthy.json"), "database", "non-primary"
        )
        self.assertEqual(selection.unit, "database/2")
        self.assertEqual(
            selection.excluded[0],
            backup.Exclusion("database/1", ("agent is lost",)),
        )

    def test_single_unit_is_selected(self):
        selection = backup.select_backup_unit(
            self.fixture("single-unit.json"), "database", "non-primary"
        )
        self.assertEqual(selection.unit, "database/0")
        self.assertTrue(selection.degraded)
        self.assertEqual(
            selection.warning, "no eligible non-primary unit; selected the primary"
        )

    def test_rejects_ambiguous_primary(self):
        with self.assertRaisesRegex(backup.SelectionError, "exactly one"):
            backup.select_backup_unit(
                self.fixture("ambiguous-primary.json"), "database", "non-primary"
            )

    def test_action_inputs_are_passed_through(self):
        backup_target = backup.target_from_action_inputs(
            {
                "MODEL": "model:variant",
                "MODEL_OWNER": "owner",
                "APPLICATION": "database_app",
                "ACTION": "custom_action",
                "PARAMETERS_JSON": '{"nested":{"enabled":true}}',
                "UNIT_ROLE": "any",
                "TIMEOUT": "45s",
            }
        )
        self.assertEqual(backup_target.qualified_model, "owner/model:variant")
        self.assertEqual(backup_target.action, "custom_action")
        self.assertEqual(backup_target.parameters, {"nested": {"enabled": True}})
        self.assertEqual(backup_target.unit_role, "any")
        self.assertEqual(backup_target.timeout, "45s")

    def test_invalid_parameter_json_fails(self):
        with self.assertRaises(json.JSONDecodeError):
            backup.target_from_action_inputs(
                {
                    "MODEL": "demo",
                    "MODEL_OWNER": TEST_MODEL_OWNER,
                    "APPLICATION": "database",
                    "PARAMETERS_JSON": "{",
                }
            )

    def test_action_model_owner_qualifies_model(self):
        backup_target = backup.target_from_action_inputs(
            {
                **DEFAULT_ACTION_INPUTS,
                "MODEL": "database-model",
                "MODEL_OWNER": TEST_MODEL_OWNER,
                "APPLICATION": "database",
            }
        )

        self.assertEqual(
            backup_target.qualified_model,
            f"{TEST_MODEL_OWNER}/database-model",
        )

    def test_model_owner_is_optional(self):
        backup_target = backup.target_from_action_inputs(
            {
                **DEFAULT_ACTION_INPUTS,
                "MODEL": "database-model",
                "APPLICATION": "database",
            }
        )

        self.assertEqual(backup_target.qualified_model, "database-model")

    def test_model_is_required(self):
        with self.assertRaisesRegex(ValueError, "model is required"):
            backup.target_from_action_inputs(
                {"MODEL_OWNER": TEST_MODEL_OWNER, "APPLICATION": "database"}
            )

    def test_application_is_required(self):
        with self.assertRaisesRegex(ValueError, "application is required"):
            backup.target_from_action_inputs(
                {"MODEL": "database-model", "MODEL_OWNER": TEST_MODEL_OWNER}
            )

    def test_summary_text_flattens_markdown_and_newlines(self):
        self.assertEqual(
            backup_helpers.summary_text("line one\nline two\r`code`"),
            "line one line two 'code'",
        )

    def test_selection_failure_summary_includes_reason(self):
        runner = FakeRunner(self.fixture("ambiguous-primary.json"))
        target = backup.BackupTarget(
            model="ambiguous-model",
            application="database",
            model_owner=TEST_MODEL_OWNER,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = backup.run_target(
                target,
                dry_run=True,
                output_path=root / "github-output",
                command_runner=runner,
                temporary_root=root,
            )
            records = read_records(root / "github-output")

        self.assertEqual(result, 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["target"], "ambiguous-model/database")
        self.assertEqual(records[0]["operation"], "backup")
        self.assertEqual(records[0]["result"], "❌ Failure")
        self.assertIsNone(records[0]["unit"])
        self.assertIn(
            "exactly one unit with status message Primary", records[0]["notes"]
        )

    def test_dry_run_skips_backup_and_lists_backups(self):
        runner = FakeRunner(self.fixture("healthy-three.json"))
        target = backup.BackupTarget(
            model="dry-run",
            application="database",
            model_owner=TEST_MODEL_OWNER,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = backup.run_target(
                    target,
                    dry_run=True,
                    output_path=root / "github-output",
                    command_runner=runner,
                    temporary_root=root,
                )
            records = read_records(root / "github-output")

        run_commands = [command for command in runner.commands if command[1] == "run"]
        self.assertEqual(result, 0)
        self.assertEqual(
            [FakeRunner._action(command) for command in run_commands],
            ["list-backups"],
        )
        self.assertIn("backup-2026-07-22", stdout.getvalue())
        self.assertIn("list warning", stderr.getvalue())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["target"], "dry-run/database")
        self.assertEqual(records[0]["unit"], "database/1")
        self.assertEqual(records[0]["result"], "⏭️ Dry run")
        self.assertEqual(
            records[0]["notes"], "Selection validated; backup action not run"
        )

    def test_status_failure_summary_omits_unit(self):
        runner = FakeRunner(self.fixture("healthy-three.json"), fail_status=True)
        target = backup.BackupTarget(
            model="unavailable-model",
            application="database",
            model_owner=TEST_MODEL_OWNER,
        )
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with redirect_stderr(stderr):
                result = backup.run_target(
                    target,
                    dry_run=False,
                    output_path=root / "github-output",
                    command_runner=runner,
                    temporary_root=root,
                )
            records = read_records(root / "github-output")

        self.assertEqual(result, 1)
        self.assertIn("command output was withheld", stderr.getvalue())
        self.assertNotIn("simulated status failure", stderr.getvalue())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["target"], "unavailable-model/database")
        self.assertEqual(records[0]["result"], "❌ Failure")
        self.assertEqual(records[0]["notes"], "Unable to read Juju status")
        self.assertIsNone(records[0]["unit"])

    def test_command_launch_error_returns_nonzero_and_captures_error(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            stdout = root / "stdout"
            stderr = root / "stderr"
            result = backup_helpers.run_command(
                ["executable-that-does-not-exist"], stdout, stderr
            )

            self.assertNotEqual(result, 0)
            self.assertEqual(stdout.read_text(), "")
            self.assertIn("executable-that-does-not-exist", stderr.read_text())

    def test_juju_run_parser_rejects_invalid_operation_envelopes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output.json"
            for response in ({}, [], {"database/0": "completed"}):
                with self.subTest(response=response):
                    output.write_text(json.dumps(response))
                    self.assertFalse(backup_helpers.juju_run_succeeded(output))

    def test_builds_action_argument_list(self):
        runner = FakeRunner(self.fixture("healthy-three.json"))
        target = backup.BackupTarget(
            model="successful-model",
            application="database",
            model_owner=TEST_MODEL_OWNER,
            parameters={
                "force": True,
                "label": "nightly backup",
                "nested": {"enabled": True},
            },
            timeout="42m",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = backup.run_target(
                target,
                dry_run=False,
                output_path=root / "github-output",
                command_runner=runner,
                temporary_root=root,
            )
            records = read_records(root / "github-output")

        action_command = next(
            command for command in runner.commands if command[1] == "run"
        )
        self.assertEqual(result, 0)
        self.assertEqual(
            [FakeRunner._model(command) for command in runner.commands],
            [f"{TEST_MODEL_OWNER}/successful-model"] * 3,
        )
        self.assertIn("force=true", action_command)
        self.assertIn("label=nightly backup", action_command)
        self.assertIn('nested={"enabled":true}', action_command)
        self.assertIn("--wait=42m", action_command)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["target"], "successful-model/database")
        self.assertEqual(records[0]["result"], "✅ Success")

    def test_lists_backups_and_prints_output_after_success(self):
        runner = FakeRunner(self.fixture("healthy-three.json"))
        target = backup.BackupTarget(
            model="successful-model",
            application="database",
            model_owner=TEST_MODEL_OWNER,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = backup.run_target(
                    target,
                    dry_run=False,
                    output_path=root / "github-output",
                    command_runner=runner,
                    temporary_root=root,
                )

        run_commands = [command for command in runner.commands if command[1] == "run"]
        self.assertEqual(result, 0)
        self.assertEqual(
            [FakeRunner._action(command) for command in run_commands],
            ["create-backup", "list-backups"],
        )
        self.assertEqual(FakeRunner._unit(run_commands[1]), "database/1")
        self.assertIn("backup-2026-07-22", stdout.getvalue())
        self.assertIn("list warning", stderr.getvalue())

    def test_degraded_success_uses_warning_result(self):
        runner = FakeRunner(self.fixture("unhealthy-replicas.json"))
        target = backup.BackupTarget(
            model="degraded-model",
            application="database",
            model_owner=TEST_MODEL_OWNER,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = backup.run_target(
                target,
                dry_run=False,
                output_path=root / "github-output",
                command_runner=runner,
                temporary_root=root,
            )
            records = read_records(root / "github-output")

        self.assertEqual(result, 0)
        self.assertEqual(records[0]["result"], "⚠️ Success (degraded)")

    def test_failed_action_returns_failure(self):
        runner = FakeRunner(
            self.fixture("healthy-three.json"),
            fail_model=f"{TEST_MODEL_OWNER}/failed-model",
        )
        target = backup.BackupTarget(
            model="failed-model",
            application="database",
            model_owner=TEST_MODEL_OWNER,
            unit_role="primary",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = backup.run_target(
                target,
                dry_run=False,
                output_path=root / "github-output",
                command_runner=runner,
                temporary_root=root,
            )
            records = read_records(root / "github-output")

        self.assertEqual(result, 1)
        self.assertEqual(records[0]["target"], "failed-model/database")
        self.assertEqual(records[0]["unit"], "database/0")
        self.assertEqual(records[0]["result"], "❌ Failure")
        self.assertIn("Backup action failed", records[0]["notes"])

    def test_failed_action_status_returns_failure_when_cli_succeeds(self):
        runner = FakeRunner(
            self.fixture("healthy-three.json"), failed_action="create-backup"
        )
        target = backup.BackupTarget(
            model="failed-model",
            application="database",
            model_owner=TEST_MODEL_OWNER,
            unit_role="primary",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = backup.run_target(
                target,
                dry_run=False,
                output_path=root / "github-output",
                command_runner=runner,
                temporary_root=root,
            )
            records = read_records(root / "github-output")

        run_commands = [command for command in runner.commands if command[1] == "run"]
        self.assertEqual(result, 1)
        self.assertEqual(
            [FakeRunner._action(command) for command in run_commands],
            ["create-backup"],
        )
        self.assertEqual(records[0]["result"], "❌ Failure")
        self.assertIn("Backup action failed", records[0]["notes"])

    def test_failed_list_status_returns_failure_when_cli_succeeds(self):
        runner = FakeRunner(
            self.fixture("healthy-three.json"), failed_action="list-backups"
        )
        target = backup.BackupTarget(
            model="dry-run",
            application="database",
            model_owner=TEST_MODEL_OWNER,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = backup.run_target(
                target,
                dry_run=True,
                output_path=root / "github-output",
                command_runner=runner,
                temporary_root=root,
            )
            records = read_records(root / "github-output")

        self.assertEqual(result, 1)
        self.assertEqual(records[0]["result"], "❌ Failure")
        self.assertIn("list-backups failed during dry run", records[0]["notes"])


if __name__ == "__main__":
    unittest.main()
