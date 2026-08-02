import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";

const script = new URL("deploy-pi.sh", import.meta.url);
const deploymentScript = new URL("../deploy/deploy.sh", import.meta.url);

function run(...args) {
  return spawnSync(script.pathname, args, { encoding: "utf8" });
}

test("top-level deploy exposes internal-only and combined modes", () => {
  const result = spawnSync("bash", [deploymentScript.pathname, "--help"], { encoding: "utf8" });
  assert.equal(result.status, 0);
  assert.match(result.stdout, /deploy\/deploy\.sh --internal/);
  assert.match(result.stdout, /deploy\/deploy\.sh\s+Deploy LAN and public endpoints/);

  const invalid = spawnSync("bash", [deploymentScript.pathname, "--unknown"], {
    encoding: "utf8",
  });
  assert.notEqual(invalid.status, 0);
});

test("LAN deploy help documents the one-command interface", () => {
  const result = run("--help");
  assert.equal(result.status, 0);
  assert.match(result.stdout, /deploy-pi\.sh lan --host ADDRESS/);
  assert.match(result.stdout, /--hostname NAME/);
});

test("LAN deploy requires an explicit deployment mode and host", () => {
  const missingMode = run();
  assert.notEqual(missingMode.status, 0);
  assert.match(missingMode.stderr, /first argument must be: lan/);

  const missingHost = run("lan");
  assert.notEqual(missingHost.status, 0);
  assert.match(missingHost.stderr, /--host is required/);
});

test("LAN deploy rejects loopback, public and invalid port targets before changing services", () => {
  for (const host of ["127.0.0.2", "8.8.8.8", "fd00::1", "not-an-address"]) {
    const result = run("lan", "--host", host);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /RFC1918 IPv4 LAN address/);
  }

  const invalidPort = run("lan", "--host", "192.168.3.250", "--port", "70000");
  assert.notEqual(invalidPort.status, 0);
  assert.match(invalidPort.stderr, /invalid port/);

  const invalidHostname = run(
    "lan",
    "--host",
    "192.168.3.250",
    "--hostname",
    "bad/name",
  );
  assert.notEqual(invalidHostname.status, 0);
  assert.match(invalidHostname.stderr, /invalid --hostname/);
});
