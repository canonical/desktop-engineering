import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { clearCaCert } from "../dist/clear_ca_cert.mjs";

function writeControllers(t, content) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "clear-ca-cert-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const controllersFile = path.join(dir, "controllers.yaml");
  fs.writeFileSync(controllersFile, content, { encoding: "utf8" });
  fs.chmodSync(controllersFile, 0o600);
  return controllersFile;
}

test("clears multiline ca-cert", (t) => {
  const controllersFile = writeControllers(
    t,
    `controllers:
    jaas:
        uuid: test
        api-endpoints: [jaas.example.com:443/api]
        ca-cert: |-
          -----BEGIN CERTIFICATE-----
          certificate-data
          -----END CERTIFICATE-----
        cloud: ""
current-controller: jaas
`,
  );

  clearCaCert(controllersFile);

  assert.equal(
    fs.readFileSync(controllersFile, "utf8"),
    `controllers:
    jaas:
        uuid: test
        api-endpoints: [jaas.example.com:443/api]
        ca-cert: ""
        cloud: ""
current-controller: jaas
`,
  );
  assert.equal(fs.statSync(controllersFile).mode & 0o777, 0o600);
});

test("empty ca-cert is idempotent", (t) => {
  const content = `controllers:
    jaas:
        uuid: test
        ca-cert: ""
        cloud: ""
current-controller: jaas
`;
  const controllersFile = writeControllers(t, content);

  clearCaCert(controllersFile);

  assert.equal(fs.readFileSync(controllersFile, "utf8"), content);
});

test("missing ca-cert raises", (t) => {
  const controllersFile = writeControllers(
    t,
    `controllers:
    jaas:
        uuid: test
current-controller: jaas
`,
  );

  assert.throws(() => clearCaCert(controllersFile), Error);
});
