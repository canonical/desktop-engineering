"""Shared command, parsing, and reporting helpers for database backup scripts."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CommandRunner = Callable[[Sequence[str], Path, Path], int]


@dataclass(frozen=True)
class CommandCapture:
    """Files capturing one command's stdout and stderr."""

    stdout: Path
    stderr: Path

    @classmethod
    def create(cls, directory: Path, name: str) -> CommandCapture:
        """Create predictable capture paths for a command in ``directory``."""

        return cls(directory / f"{name}.json", directory / f"{name}.err")

    def run(self, runner: CommandRunner, command: Sequence[str]) -> int:
        """Run ``command`` with this capture pair and return its exit status."""

        return runner(command, self.stdout, self.stderr)

    def print(self) -> None:
        """Print both captured streams; use only for non-sensitive output."""

        sys.stdout.write(self.stdout.read_text())
        sys.stderr.write(self.stderr.read_text())


def run_command(command: Sequence[str], stdout_path: Path, stderr_path: Path) -> int:
    """Run a command with both streams captured, returning 127 on launch error."""

    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        try:
            return subprocess.run(
                command, stdout=stdout, stderr=stderr, check=False
            ).returncode
        except OSError as error:
            message = f"Unable to execute {command[0]}: {error}\n"
            stderr.write(message.encode(errors="replace"))
            return 127


def read_json_object(path: Path) -> dict[str, Any]:
    """Read a JSON object, rejecting arrays and scalar top-level values."""

    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError("JSON document is not an object")
    return value


def juju_operations(output_path: Path) -> tuple[Mapping[str, Any], ...]:
    """Parse Juju's non-empty operation mapping into operation values."""

    response = read_json_object(output_path)
    if not response or not all(
        isinstance(operation, dict) for operation in response.values()
    ):
        raise ValueError("Juju output does not contain operations")
    return tuple(response.values())


def juju_run_succeeded(stdout_path: Path) -> bool:
    """Return whether Juju emitted one or more completed operations."""

    try:
        operations = juju_operations(stdout_path)
    except (json.JSONDecodeError, OSError, ValueError):
        return False
    return all(operation.get("status") == "completed" for operation in operations)


def parameter_value(value: Any) -> str:
    """Serialize one action parameter into Juju's command-line representation."""

    if isinstance(value, bool):
        return str(value).lower()
    if value is None or isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


def join_notes(*notes: str | None) -> str:
    """Join non-empty summary notes with consistent punctuation."""

    return "; ".join(note for note in notes if note)


def set_result_output(
    output_path: Path | None,
    *,
    operation: str,
    target: str,
    result: str,
    notes: str,
    unit: str | None = None,
) -> None:
    """Publish one run's outcome as a JSON step output."""

    record = {
        "operation": summary_text(operation),
        "target": summary_text(target),
        "result": summary_text(result),
        "notes": summary_text(notes),
        "unit": summary_text(unit) if unit is not None else None,
    }
    value = json.dumps(record, separators=(",", ":"))
    if output_path is None:
        print(value)
    else:
        with output_path.open("a") as output:
            output.write(f"result={value}\n")


def summary_text(value: str) -> str:
    """Flatten untrusted text so it cannot inject extra summary lines or inline code."""

    return (
        value.replace("\n", " ")
        .replace("\r", " ")
        .replace("`", "'")
        .replace("|", "\\|")
    )
