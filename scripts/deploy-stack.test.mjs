import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const cpuScript = fileURLToPath(new URL("deploy-cpu.sh", import.meta.url));
const gpuScript = fileURLToPath(new URL("deploy-gpu.sh", import.meta.url));

function resolveBash() {
  if (process.env.ONEIROI_TEST_BASH) return process.env.ONEIROI_TEST_BASH;
  if (process.platform !== "win32") return "bash";
  const candidates = [
    path.join(process.env.ProgramFiles ?? "C:\\Program Files", "Git", "bin", "bash.exe"),
    path.join(process.env.LOCALAPPDATA ?? "", "Programs", "Git", "bin", "bash.exe"),
  ];
  return candidates.find((candidate) => existsSync(candidate)) ?? "bash";
}

const bash = resolveBash();

function run(script, ...args) {
  return spawnSync(bash, [script, ...args], { encoding: "utf8" });
}

test("deploy-cpu help documents the one-command interface", () => {
  const result = run(cpuScript, "--help");
  assert.equal(result.status, 0);
  assert.match(result.stdout, /deploy-cpu\.sh \[options\]/);
  assert.match(result.stdout, /--branch NAME/);
  assert.match(result.stdout, /--skip-pull/);
});

test("deploy-cpu rejects unknown arguments and requires an assigned LAN host", () => {
  const unknown = run(cpuScript, "--bogus");
  assert.notEqual(unknown.status, 0);
  assert.match(unknown.stderr, /unknown argument: --bogus/);

  const invalidPort = run(cpuScript, "--port", "not-a-port");
  assert.notEqual(invalidPort.status, 0);
  assert.match(invalidPort.stderr, /invalid port/);
});

test("deploy-gpu help documents the one-command interface", () => {
  const result = run(gpuScript, "--help");
  assert.equal(result.status, 0);
  assert.match(result.stdout, /deploy-gpu\.sh \[options\]/);
  assert.match(result.stdout, /--checkout PATH/);
  assert.match(result.stdout, /--config-dir PATH/);
});

test("deploy-gpu rejects unknown arguments and missing required commands", () => {
  const unknown = run(gpuScript, "--bogus");
  assert.notEqual(unknown.status, 0);
  assert.match(unknown.stderr, /unknown argument: --bogus/);

  const missingCheckout = run(gpuScript, "--checkout", "/definitely/not/here");
  assert.notEqual(missingCheckout.status, 0);
  assert.match(missingCheckout.stderr, /checkout is missing its git metadata/);
});
