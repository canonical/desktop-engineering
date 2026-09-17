import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ACTION_PATH = Path(__file__).resolve().parents[1] / "action.yaml"
ACTION = yaml.safe_load(ACTION_PATH.read_text())
STEPS = {step["name"]: step for step in ACTION["runs"]["steps"]}
NODE = os.environ.get("NODE", "node")
RUNNER = r"""
const fs = require('node:fs');
const childProcess = require('node:child_process');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const outputs = {};
const calls = [];
const masks = [];
const core = {
  setOutput: (name, value) => outputs[name] = String(value),
  setFailed: (message) => { throw new Error(message); },
  setSecret: (value) => masks.push(value),
  info: () => {},
};
const localRequire = (name) => name !== 'node:child_process' ? require(name) : {
  execFileSync(command, args, options = {}) {
    calls.push({command, args});
    if (command === 'git') {
      if (input.failCommand && args.includes(input.failCommand)) {
        throw new Error(`Simulated ${input.failCommand} failure`);
      }
      if (args.includes('fetch')) {
        args = args.map(arg => arg.startsWith('https://') ? input.upstream : arg);
      }
      if (args.includes('push')) {
        if (input.raceHead) {
          childProcess.execFileSync('git', ['--git-dir', input.fork, 'update-ref',
            'refs/heads/translations', input.raceHead]);
        }
        args = args.map(arg => arg.startsWith('https://') ? input.fork : arg);
      }
      if (args.some(arg => arg.startsWith('https://'))) throw new Error('Network access forbidden in tests');
    }
    return childProcess.execFileSync(command, args, options);
  },
};
const github = {
  rest: {
    pulls: {get: async () => ({data: input.currentPR})},
    users: {getAuthenticated: async () => ({data: {id: 1, login: 'test-bot'}})},
  },
  paginate: async () => input.signingKeys || [],
};
(async () => {
  let error;
  try {
    const script = new AsyncFunction('require', 'context', 'github', 'core', input.script);
    if (!input.syntaxOnly) await script(localRequire, input.context, github, core);
  } catch (caught) {
    error = caught.message;
  }
  console.log(JSON.stringify({outputs, error, calls, masks}));
})();
"""


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.environment = {
            **os.environ,
            "HOME": str(self.root),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GITHUB_SERVER_URL": "https://github.com",
            "RUNNER_TEMP": str(self.root),
            "READ_TOKEN": "test-read-token",
            "BOT_TOKEN": "test-bot-token",
            "COMMIT_MESSAGE": "maint: regenerate l10n",
            "GENERATED_FILE_PATTERNS": STEPS["Validate generated files"]["env"]["GENERATED_FILE_PATTERNS"],
            "TRANSLATED_FILE_PATTERNS": STEPS["Validate pull request files"]["env"]["TRANSLATED_FILE_PATTERNS"],
        }
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        for filename in ("README.md", "melos.yaml", "l10n/app.arb", "l10n/app.dart", "app.desktop"):
            self.write(filename, "baseline\n")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.base = self.git("rev-parse", "HEAD")
        self.upstream = self.root / "upstream.git"
        self.fork = self.root / "fork.git"
        self.git("clone", "--bare", str(self.repo), str(self.upstream))
        self.git("clone", "--bare", str(self.repo), str(self.fork))
        self.pr = {
            "number": 1,
            "state": "open",
            "user": {"login": "weblate"},
            "head": {
                "sha": self.base,
                "ref": "translations",
                "repo": {"name": "fixture", "full_name": "weblate/fixture", "owner": {"login": "weblate"}},
            },
            "base": {"sha": self.base, "ref": "main", "repo": {"full_name": "canonical/fixture"}},
        }
        self.record_existing_files()

    def record_existing_files(self):
        result = self.run_step("Record existing files")
        self.assert_success(result)
        self.environment["EXISTING_FILES"] = str(Path(result["outputs"]["directory"]) / "files")

    def git(self, *arguments):
        return subprocess.check_output(
            ["git", *arguments], cwd=self.repo, env=self.environment, stderr=subprocess.PIPE,
        ).decode().strip()

    def write(self, filename, content):
        target = self.repo / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "PR change")
        self.pr["head"]["sha"] = self.git("rev-parse", "HEAD")

    def run_step(self, name, *, context=None, environment=None, **options):
        step = STEPS[name]
        env = {**self.environment, **(environment or {})}
        if "run" in step:
            self.assertNotIn("${{", step["run"], f"Step '{name}' needs expression interpolation")
            with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as handle:
                output_path = Path(handle.name)
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-euo", "pipefail", "-c", step["run"]],
                text=True, capture_output=True, cwd=self.repo,
                env={**env, "GITHUB_OUTPUT": str(output_path)},
            )
            outputs = {}
            for line in output_path.read_text().splitlines():
                key, _, value = line.partition("=")
                outputs[key] = value
            output_path.unlink()
            parsed = {"outputs": outputs}
            if result.returncode != 0:
                parsed["error"] = result.stderr.strip()
            return parsed
        default_context = {
            "eventName": "pull_request_target", "repo": {"owner": "canonical", "repo": "fixture"},
            "payload": {"action": "opened", "sender": {"login": "weblate"}, "pull_request": self.pr},
        }
        result = subprocess.run(
            [NODE, "-e", RUNNER],
            input=json.dumps({
                "script": step["with"]["script"], "context": context or default_context,
                "currentPR": self.pr, "upstream": str(self.upstream), "fork": str(self.fork), **options,
            }),
            text=True, capture_output=True, cwd=self.repo,
            env=env, check=True,
        )
        return json.loads(result.stdout)

    def assert_success(self, result):
        self.assertNotIn("error", result, result.get("error"))

    def test_inline_syntax(self):
        for name, step in STEPS.items():
            with self.subTest(step=name):
                if "script" in step.get("with", {}):
                    self.assert_success(self.run_step(name, syntaxOnly=True))
                if "run" in step and "${{" not in step["run"]:
                    subprocess.run(["bash", "-n"], input=step["run"], text=True, check=True)

    def test_fixed_generation_configuration(self):
        self.assertEqual(set(ACTION["inputs"]), {"github-token", "ssh-signing-private-key"})
        self.assertEqual(STEPS["Generate localization files"]["run"], "melos gen-l10n")
        self.assertEqual(
            STEPS["Validate pull request files"]["env"]["TRANSLATED_FILE_PATTERNS"],
            r"(^|/)l10n/(?:[^/]+/)*[^/]+\.arb$" "\n" r"\.html$",
        )
        self.assertEqual(
            STEPS["Validate pull request files"]["env"]["GENERATED_FILE_PATTERNS"],
            r"(^|/)l10n/(?:[^/]+/)*[^/]+\.dart$" "\n" r"\.desktop$",
        )
        self.assertIs(
            STEPS["Validate pull request files"]["env"]["GENERATED_FILE_PATTERNS"],
            STEPS["Validate generated files"]["env"]["GENERATED_FILE_PATTERNS"],
        )

    def test_event_identity_and_sender_policy(self):
        for action, sender, eligible in (("opened", "weblate", "true"), ("reopened", "maintainer", "true"), ("synchronize", "test-bot", "false"), ("synchronize", "weblate", "true")):
            context = {"eventName": "pull_request_target", "repo": {"owner": "canonical", "repo": "fixture"}, "payload": {"action": action, "sender": {"login": sender}, "pull_request": self.pr}}
            with self.subTest(action=action, sender=sender):
                result = self.run_step("Validate pull request", context=context)
                self.assert_success(result)
                self.assertEqual(result["outputs"]["eligible"], eligible)
        for field in ("author", "owner", "deleted", "closed", "base"):
            saved = copy.deepcopy(self.pr)
            with self.subTest(field=field):
                if field == "author":
                    self.pr["user"]["login"] = "someone-else"
                elif field == "owner":
                    self.pr["head"]["repo"]["owner"]["login"] = "someone-else"
                elif field == "deleted":
                    self.pr["head"]["repo"] = None
                elif field == "closed":
                    self.pr["state"] = "closed"
                else:
                    self.pr["base"]["repo"]["full_name"] = "other/repo"
                self.assertIn("error", self.run_step("Validate pull request"))
            self.pr = saved

    def test_allowed_paths(self):
        for filename in ("apps/l10n/nested/app.arb", "l10n/app.dart", "docs/help.html", "assets/app.desktop"):
            self.write(filename, "translation")
        self.commit()
        self.assert_success(self.run_step("Validate pull request files"))
        self.write("messages.po", "translation")
        self.commit()
        self.assertIn("Unexpected PR path", self.run_step("Validate pull request files")["error"])

    def test_disallowed_generator_and_arb_outside_l10n(self):
        for filename in ("melos.yaml", "scripts/generate.py", "app.arb", "notl10n/app.dart", "l10n/script.sh"):
            with self.subTest(filename=filename):
                self.git("reset", "--hard", self.base)
                self.git("clean", "-fd")
                self.write(filename, "changed")
                self.commit()
                self.assertIn("Unexpected PR path", self.run_step("Validate pull request files")["error"])

    def test_rename_checks_old_path(self):
        self.git("mv", "README.md", "l10n/readme.dart")
        self.commit()
        self.assertIn("README.md", self.run_step("Validate pull request files")["error"])

    def test_large_diff_and_immutable_head(self):
        for index in range(3001):
            self.write(f"l10n/app_{index}.arb", "translation")
        self.write("zz-generator.sh", "changed")
        self.commit()
        self.assertIn("zz-generator.sh", self.run_step("Validate pull request files")["error"])
        self.pr["head"]["sha"] = self.base
        self.assertIn("Checkout does not match", self.run_step("Validate pull request files")["error"])

    def test_pr_file_modes_and_missing_ancestry(self):
        self.write("l10n/new.arb", "data").chmod(0o755)
        self.commit()
        self.assertIn("file type", self.run_step("Validate pull request files")["error"])
        self.git("reset", "--hard", self.base)
        (self.repo / "l10n/link.arb").symlink_to("../melos.yaml")
        self.commit()
        self.assertIn("file type", self.run_step("Validate pull request files")["error"])
        self.git("reset", "--hard", self.base)
        self.git("update-index", "--add", "--cacheinfo", f"160000,{self.base},l10n/module.arb")
        self.git("commit", "-qm", "gitlink")
        self.pr["head"]["sha"] = self.git("rev-parse", "HEAD")
        self.assertIn("file type", self.run_step("Validate pull request files")["error"])
        self.pr["base"]["sha"] = "f" * 40
        self.assertIn("error", self.run_step("Validate pull request files"))

    def test_output_noop_and_staged_worktree_cancellation(self):
        result = self.run_step("Validate generated files")
        self.assert_success(result)
        self.assertEqual(result["outputs"], {"changed": "false"})
        self.write("l10n/app.dart", "temporary")
        self.git("add", ".")
        self.write("l10n/app.dart", "baseline\n")
        result = self.run_step("Validate generated files")
        self.assert_success(result)
        self.assertEqual(result["outputs"], {"changed": "false"})
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")

    def test_staged_unstaged_untracked_deleted_and_literal_names(self):
        self.write("l10n/app.dart", "staged output")
        self.git("add", ".")
        filenames = ["l10n/sp ace.dart", "l10n/new\nline.dart", "l10n/[ab].dart", "l10n/a.dart", ":(glob)*.desktop"]
        for filename in filenames:
            self.write(filename, "output")
        (self.repo / "app.desktop").unlink()
        result = self.run_step("Validate generated files")
        self.assert_success(result)
        self.assertEqual(result["outputs"]["changed"], "true")
        self.assertEqual(result["outputs"]["tree"], self.git("write-tree"))
        self.assertEqual(set(self.git("diff", "--cached", "--name-only", "-z").split("\0")[:-1]), set(filenames + ["l10n/app.dart", "app.desktop"]))
        self.assertEqual((self.repo / "l10n/app.dart").read_text(), "staged output")

    def test_new_ignored_files_fail_validation(self):
        self.write(".git/info/exclude", "l10n/ignored*\n*.desktop\nbuild/\n")
        for filename in ("l10n/ignored.dart", "l10n/ignored\nline.dart", ":(glob)*.desktop", "build/cache.bin"):
            for staged in (False, True):
                with self.subTest(filename=filename, staged=staged):
                    target = self.write(filename, "generated output")
                    if staged:
                        self.git("--literal-pathspecs", "add", "-f", "--", filename)
                    result = self.run_step("Validate generated files")
                    self.assertIn("Generation created an ignored file", result.get("error", ""))
                    self.assertIn(json.dumps(filename), result["error"])
                    self.assertEqual(result["outputs"], {})
                    self.git("read-tree", self.base)
                    target.unlink()

    def test_ignore_rules_and_tracked_outputs(self):
        self.write(".gitignore", "l10n/*.dart\n!l10n/included.dart\n")
        self.commit()
        self.record_existing_files()
        self.write("l10n/app.dart", "tracked output")
        self.write("l10n/included.dart", "included output")
        result = self.run_step("Validate generated files")
        self.assert_success(result)
        self.assertEqual(result["outputs"]["changed"], "true")
        before = self.git("write-tree")
        self.write("l10n/excluded.dart", "ignored output")
        result = self.run_step("Validate generated files")
        self.assertIn('Generation created an ignored file: "l10n/excluded.dart"', result["error"])
        self.assertEqual(result["outputs"], {})
        self.assertEqual(self.git("write-tree"), before)

    def test_generation_snapshot_and_ignore_check_fail_closed(self):
        self.write("l10n/new.dart", "output")
        result = self.run_step("Validate generated files", failCommand="check-ignore")
        self.assertIn("Simulated check-ignore failure", result["error"])
        self.assertEqual(result["outputs"], {})
        Path(self.environment["EXISTING_FILES"]).unlink()
        result = self.run_step("Validate generated files")
        self.assertIn("error", result)
        self.assertEqual(result["outputs"], {})

    def test_ignored_artifacts_and_cancelled_staged_outputs(self):
        self.write(".git/info/exclude", "l10n/ignored*\nbuild/\n")
        artifact = self.write("build/app.desktop", "ignored artifact")
        self.write("l10n/ignored_artifact.dart", "ignored artifact")
        self.record_existing_files()
        result = self.run_step("Validate generated files")
        self.assert_success(result)
        self.assertEqual(result["outputs"], {"changed": "false"})
        cancelled = self.write("l10n/ignored_cancelled.dart", "temporary output")
        self.git("add", "-f", "--", "l10n/ignored_cancelled.dart")
        cancelled.unlink()
        self.write("l10n/app.dart", "temporary output")
        self.git("add", "--", "l10n/app.dart")
        self.write("l10n/app.dart", "baseline\n")
        result = self.run_step("Validate generated files")
        self.assert_success(result)
        self.assertEqual(result["outputs"], {"changed": "false"})
        self.assertEqual(self.git("write-tree"), self.git("rev-parse", f"{self.base}^{{tree}}"))
        self.assertFalse(cancelled.exists())
        self.assertEqual(artifact.read_text(), "ignored artifact")
        self.git("add", "-f", "--", "l10n/ignored_artifact.dart")
        result = self.run_step("Validate generated files")
        self.assertIn("Generation created an ignored file", result["error"])
        self.assertEqual(result["outputs"], {})

    def test_unexpected_changes_even_when_hidden_in_index(self):
        for staged, revert_worktree in ((False, False), (True, False), (True, True)):
            with self.subTest(staged=staged, revert=revert_worktree):
                self.git("reset", "--hard", self.base)
                self.write("README.md", "unexpected")
                if staged:
                    self.git("add", "README.md")
                if revert_worktree:
                    self.write("README.md", "baseline\n")
                self.write("l10n/app.dart", "output")
                self.assertIn("unexpected path", self.run_step("Validate generated files")["error"])

    def test_output_symlinks_modes_and_moved_head(self):
        target = self.repo / "l10n/link.dart"
        target.symlink_to("../README.md")
        self.assertIn("non-regular", self.run_step("Validate generated files")["error"])
        self.git("add", ".")
        self.assertIn("file type", self.run_step("Validate generated files")["error"])
        self.git("reset", "--hard", self.base)
        self.write("l10n/executable.dart", "output").chmod(0o755)
        self.assertIn("file type", self.run_step("Validate generated files")["error"])
        self.git("commit", "--allow-empty", "-qm", "generator commit")
        self.assertIn("must not create commits", self.run_step("Validate generated files")["error"])

    def prepare_publish(self):
        self.write("l10n/app.arb", "translation")
        self.commit()
        self.git("push", str(self.fork), "HEAD:refs/heads/translations")
        self.write("l10n/app.dart", "output")
        result = self.run_step("Validate generated files")
        self.assert_success(result)
        key = self.root / "fixture-key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
        self.environment.update({"EXPECTED_TREE": result["outputs"]["tree"], "SSH_SIGNING_PRIVATE_KEY": key.read_text()})
        return [{"key": key.with_suffix(".pub").read_text()}]

    def assert_cleaned(self, result):
        self.assertFalse(list(self.root.glob("weblate-l10n-*")))
        if "directory" in result["outputs"]:
            self.assertFalse(Path(result["outputs"]["directory"]).exists())

    def test_signed_push_contains_only_validated_output_and_no_hooks(self):
        keys = self.prepare_publish()
        self.write(".git/info/exclude", "build/\n")
        self.write("build/app.desktop", "ignored artifact")
        self.record_existing_files()
        self.write("l10n/staged.dart", "staged output")
        self.git("add", "--", "l10n/staged.dart")
        generated = self.run_step("Validate generated files")
        self.assert_success(generated)
        self.environment["EXPECTED_TREE"] = generated["outputs"]["tree"]
        for hook in ("prepare-commit-msg", "post-commit", "pre-push"):
            self.write(f".git/hooks/{hook}", "#!/bin/sh\nexit 1\n").chmod(0o755)
        result = self.run_step("Commit and push generated files", signingKeys=keys)
        self.assert_success(result)
        self.assert_cleaned(result)
        commit = self.git("rev-parse", "HEAD")
        self.assertEqual(self.git("show", "-s", "--format=%P", "HEAD"), self.pr["head"]["sha"])
        self.assertEqual(self.git("diff", "--name-only", "HEAD^", "HEAD"), "l10n/app.dart\nl10n/staged.dart")
        self.assertEqual(self.git("--git-dir", str(self.fork), "rev-parse", "translations"), commit)
        self.assertEqual(self.git("--git-dir", str(self.fork), "show", "translations:l10n/staged.dart"), "staged output")
        self.assertIn("gpgsig -----BEGIN SSH SIGNATURE-----", self.git("cat-file", "commit", commit))
        self.assertTrue(any("verify-commit" in call["args"] for call in result["calls"]))
        self.assertEqual(len(result["masks"]), 1)
        self.assertNotIn("test-bot-token", (self.repo / ".git/config").read_text())

    def test_signing_and_push_failures_clean_up(self):
        keys = self.prepare_publish()
        for options, expected in (({"signingKeys": []}, "not registered"), ({"signingKeys": keys, "failCommand": "commit"}, "Simulated commit"), ({"signingKeys": keys, "failCommand": "push"}, "Push rejected")):
            with self.subTest(options=options.keys(), expected=expected):
                result = self.run_step("Commit and push generated files", **options)
                self.assertIn(expected, result["error"])
                self.assert_cleaned(result)

    def test_publish_ignores_generator_git_configuration(self):
        keys = self.prepare_publish()
        marker = self.root / "signing-helper-ran"
        helper = self.write(
            ".git/signing-helper",
            f"#!/bin/sh\ntouch '{marker}'\nexit 1\n",
        )
        helper.chmod(0o755)
        config = self.write(".git/helper.config", f'[gpg "ssh"]\nprogram = {helper}\n')
        for source in ("local", "include", "worktree", "global", "environment", "parameters", "push-url"):
            with self.subTest(source=source):
                self.git("reset", "--soft", self.pr["head"]["sha"])
                self.git("read-tree", self.environment["EXPECTED_TREE"])
                environment = {}
                if source == "local":
                    self.git("config", "gpg.ssh.program", str(helper))
                elif source == "include":
                    self.git("config", "include.path", str(config))
                elif source == "worktree":
                    self.git("config", "extensions.worktreeConfig", "true")
                    self.write(".git/config.worktree", config.read_text())
                elif source == "global":
                    environment = {"GIT_CONFIG_GLOBAL": str(config)}
                elif source == "environment":
                    environment = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "gpg.ssh.program", "GIT_CONFIG_VALUE_0": str(helper)}
                elif source == "parameters":
                    environment = {"GIT_CONFIG_PARAMETERS": f"'gpg.ssh.program={helper}'"}
                else:
                    self.git("config", "protocol.ext.allow", "always")
                    self.git("config", f"url.ext::{helper}.insteadOf", str(self.fork))
                result = self.run_step("Commit and push generated files", signingKeys=keys, environment=environment)
                self.assertFalse(marker.exists(), "Generator-configured helper ran during publication")
                self.assert_success(result)
                self.assert_cleaned(result)
                self.assertEqual(self.git("rev-parse", "HEAD^{tree}"), self.environment["EXPECTED_TREE"])
                self.assertEqual(self.git("show", "-s", "--format=%P", "HEAD"), self.pr["head"]["sha"])
                self.assertEqual(self.git("--git-dir", str(self.fork), "rev-parse", "translations"), self.git("rev-parse", "HEAD"))
                self.git("--git-dir", str(self.fork), "update-ref", "refs/heads/translations", self.pr["head"]["sha"])

    def test_publish_rejects_shared_git_directory(self):
        keys = self.prepare_publish()
        self.write(".git/commondir", str(self.upstream))
        result = self.run_step("Commit and push generated files", signingKeys=keys)
        self.assertIn("standalone checkout", result["error"])
        self.assertEqual(result["calls"], [])
        self.assertEqual(result["outputs"], {})
        self.assert_cleaned(result)

    def test_invalid_key_and_changed_index(self):
        keys = self.prepare_publish()
        result = self.run_step("Commit and push generated files", signingKeys=keys, environment={"SSH_SIGNING_PRIVATE_KEY": "not a key"})
        self.assertIn("error", result)
        self.assert_cleaned(result)
        self.write("README.md", "unexpected")
        self.git("add", ".")
        self.assertIn("staged tree changed", self.run_step("Commit and push generated files", signingKeys=keys)["error"])

    def test_closed_or_advanced_pr_is_not_published(self):
        self.assert_success(self.run_step("Check pull request before publishing"))
        for change in ("closed", "head", "branch"):
            current = copy.deepcopy(self.pr)
            if change == "closed":
                current["state"] = "closed"
            elif change == "head":
                current["head"]["sha"] = "f" * 40
            else:
                current["head"]["ref"] = "other-branch"
            result = self.run_step("Check pull request before publishing", currentPR=current)
            self.assertIn("changed or closed", result["error"])
            self.assert_cleaned(result)

    def test_lease_rejects_remote_rewind(self):
        keys = self.prepare_publish()
        result = self.run_step("Commit and push generated files", signingKeys=keys, raceHead=self.base)
        self.assertIn("Push rejected", result["error"])
        self.assertEqual(self.git("--git-dir", str(self.fork), "rev-parse", "translations"), self.base)
        self.assert_cleaned(result)

    def test_lease_rejects_remote_advance(self):
        keys = self.prepare_publish()
        peer = self.git("commit-tree", f"{self.pr['head']['sha']}^{{tree}}", "-p", self.pr["head"]["sha"], "-m", "peer update")
        self.git("push", str(self.fork), f"{peer}:refs/heads/peer")
        result = self.run_step("Commit and push generated files", signingKeys=keys, raceHead=peer)
        self.assertIn("Push rejected", result["error"])
        self.assertEqual(self.git("--git-dir", str(self.fork), "rev-parse", "translations"), peer)
        self.assert_cleaned(result)

    def test_cleanup_step_is_idempotent_and_scoped(self):
        targets = []
        for name in ("weblate-l10n-abc", "weblate-generation-xyz"):
            directory = self.root / name
            directory.mkdir(mode=0o700)
            (directory / "key").write_text("fixture")
            targets.append(directory)
        keep = self.root / "keep-me"
        keep.mkdir()
        for _ in range(2):
            self.assert_success(self.run_step("Clean up temporary files"))
        for directory in targets:
            self.assertFalse(directory.exists())
        self.assertTrue(keep.exists())
        self.assertTrue(self.repo.exists())


if __name__ == "__main__":
    unittest.main()