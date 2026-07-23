/**
 * Clear the embedded controller CA certificate from a Juju controllers file.
 *
 * After `juju login --trust`, the controllers.yaml file embeds the
 * controller's CA certificate. Clearing it makes the Juju client fall back to
 * the runner's system CA store, which is expected to trust the JAAS endpoint
 * certificate.
 *
 * This is a workaround for https://github.com/juju/juju/pull/22931. Once that
 * fix is released to the stable Juju snap, this step can be disabled (see the
 * `clear-ca-cert` input of the jaas-auth action).
 */
import fs from "node:fs";

const CA_CERT_PREFIX = "        ca-cert:";
const CA_CERT_INDENT = 8;

/**
 * Replace the controller's ca-cert value (which may be a multiline block
 * scalar) with an empty string, preserving the file's permissions via an
 * atomic replace.
 *
 * @param {string} controllersFile Path to the controllers.yaml file.
 */
export function clearCaCert(controllersFile) {
  const lines = fs
    .readFileSync(controllersFile, "utf8")
    .split(/(?<=\n)/);

  const caCertLines = [];
  lines.forEach((line, index) => {
    if (line.startsWith(CA_CERT_PREFIX)) caCertLines.push(index);
  });
  if (caCertLines.length !== 1) {
    throw new Error(
      `expected one controller ca-cert entry, found ${caCertLines.length}`,
    );
  }

  const start = caCertLines[0];
  let end = start + 1;
  while (end < lines.length) {
    const line = lines[end];
    const indentation = line.length - line.trimStart().length;
    if (line.trim() && indentation <= CA_CERT_INDENT) break;
    end += 1;
  }

  lines.splice(start, end - start, `${CA_CERT_PREFIX} ""\n`);

  const mode = fs.statSync(controllersFile).mode & 0o7777;
  const temporaryFile = controllersFile + ".tmp";
  fs.writeFileSync(temporaryFile, lines.join(""), { encoding: "utf8" });
  fs.chmodSync(temporaryFile, mode);
  fs.renameSync(temporaryFile, controllersFile);
}
