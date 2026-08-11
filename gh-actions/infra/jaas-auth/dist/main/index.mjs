/**
 * JAAS auth — main entrypoint.
 *
 * Authenticates to the JAAS controller as a service account using the given
 * Juju client credentials, and outputs the JUJU_DATA directory holding the
 * authenticated client state. Cleanup is handled by the companion post
 * entrypoint (dist/post/index.mjs), which GitHub always runs, even when this
 * step or the job fails.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

function run(command, args, options = {}) {
  execFileSync(command, args, { stdio: "inherit", ...options });
}

function inputEnv(name) {
  return `INPUT_${name.replace(/ /g, "_").toUpperCase()}`;
}

function required(name) {
  const value = process.env[inputEnv(name)];
  if (!value) throw new Error(`missing required input: ${name}`);
  return value;
}

function input(name, fallback = "") {
  return process.env[inputEnv(name)] || fallback;
}

function appendEnv(name, value) {
  fs.appendFileSync(process.env.GITHUB_ENV, `${name}=${value}\n`);
}

try {
  const controller = required("jaas-controller");
  const controllerHost = required("jaas-controller-host");
  const clientId = required("juju-client-id");
  const clientSecret = required("juju-client-secret");

  run("sudo", ["snap", "install", "juju"]);
  run("juju", ["version"]);

  // Prepare the Juju client state directory.
  const jujuData = path.join(process.env.RUNNER_TEMP || "/tmp", "juju-data");
  fs.mkdirSync(jujuData, { recursive: true, mode: 0o700 });
  fs.chmodSync(jujuData, 0o700);

  // Mask and export the credentials for later steps in this job.
  console.log(`::add-mask::${clientId}`);
  console.log(`::add-mask::${clientSecret}`);
  appendEnv("JUJU_CLIENT_ID", clientId);
  appendEnv("JUJU_CLIENT_SECRET", clientSecret);

  const env = {
    ...process.env,
    JUJU_DATA: jujuData,
    JUJU_CLIENT_ID: clientId,
    JUJU_CLIENT_SECRET: clientSecret,
  };

  // Authenticate to JAAS.
  run(
    "juju",
    [
      "login",
      "--no-browser-login",
      "-c",
      controller,
      controllerHost,
    ],
    { env, stdio: ["inherit", "ignore", "inherit"] },
  );

  fs.appendFileSync(process.env.GITHUB_OUTPUT, `juju-data=${jujuData}\n`);
  // Persist for the post (cleanup) entrypoint.
  appendEnv("JAAS_AUTH_JUJU_DATA", jujuData);
  appendEnv("JAAS_AUTH_CLEANUP", input("cleanup", "true"));
} catch (error) {
  console.error(`::error::${error.message}`);
  process.exitCode = 1;
}
