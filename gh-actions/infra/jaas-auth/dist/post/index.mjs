/**
 * JAAS auth — post (cleanup) entrypoint.
 *
 * Runs unconditionally after the job (post-if: always()). Logs out of the Juju
 * controller and removes the client state, then clears the related environment
 * variables. All steps are best-effort so a failure does not mask the job's
 * original result. Skipped entirely when the `cleanup` input was "false".
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const jujuData =
  process.env.JAAS_AUTH_JUJU_DATA ||
  path.join(process.env.RUNNER_TEMP || "/tmp", "juju-data");

function appendEnv(name, value) {
  fs.appendFileSync(process.env.GITHUB_ENV, `${name}=${value}\n`);
}

function main() {
  if ((process.env.JAAS_AUTH_CLEANUP || "true") !== "true") {
    console.log("Skipping JAAS cleanup (cleanup input was not 'true').");
    return;
  }

  // Best-effort: log out of the controller before deleting its state. There is
  // only one controller in this JUJU_DATA, so a bare `juju logout` suffices.
  try {
    execFileSync("juju", ["logout"], {
      env: { ...process.env, JUJU_DATA: jujuData },
      stdio: "inherit",
    });
  } catch (error) {
    console.error(
      `::warning::juju logout failed; removing client state anyway: ${error.message}`,
    );
  }

  fs.rmSync(jujuData, { recursive: true, force: true });

  appendEnv("JUJU_CLIENT_ID", "");
  appendEnv("JUJU_CLIENT_SECRET", "");
  appendEnv("JUJU_DATA", "");
}

main();
