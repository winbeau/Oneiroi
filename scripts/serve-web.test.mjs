import assert from "node:assert/strict";
import { createServer, request as httpRequest } from "node:http";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import test from "node:test";

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return server.address().port;
}

async function freePort() {
  const server = createServer();
  const port = await listen(server);
  await new Promise((resolve) => server.close(resolve));
  return port;
}

async function waitForOrigin(url, child) {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`origin exited: ${child.exitCode}`);
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("origin did not become ready");
}

async function stop(child) {
  if (child.exitCode !== null) return;
  child.kill("SIGTERM");
  await new Promise((resolve) => child.once("exit", resolve));
}

async function postWithContinue(url, contentType, body) {
  return new Promise((resolve, reject) => {
    const request = httpRequest(url, {
      method: "POST",
      headers: {
        "Content-Type": contentType,
        "Content-Length": body.length,
        Expect: "100-continue",
      },
    });
    request.once("continue", () => request.end(body));
    request.once("error", reject);
    request.once("response", (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.once("end", () =>
        resolve({ status: response.statusCode, body: Buffer.concat(chunks) }),
      );
    });
    request.flushHeaders();
  });
}

test("static origin proxies bounded multipart uploads and streams range responses", async () => {
  const upstream = createServer(async (request, response) => {
    if (request.url === "/v1/uploads/images") {
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      const body = Buffer.concat(chunks);
      response.writeHead(201, { "Content-Type": "application/json" });
      response.end(
        JSON.stringify({
          contentType: request.headers["content-type"],
          body: body.toString("utf8"),
        }),
      );
      return;
    }
    if (request.url === "/v1/jobs/job-test/file") {
      response.writeHead(206, {
        "Accept-Ranges": "bytes",
        "Content-Range": "bytes 0-9/10",
        "Content-Type": "video/mp4",
      });
      response.end("0123456789");
      return;
    }
    response.writeHead(404);
    response.end();
  });
  const upstreamPort = await listen(upstream);
  const originPort = await freePort();
  const temporaryRoot = await mkdtemp(join(tmpdir(), "oneiroi-origin-"));
  await writeFile(join(temporaryRoot, "index.html"), "<!doctype html><title>Oneiroi</title>");
  const child = spawn(process.execPath, ["scripts/serve-web.mjs"], {
    cwd: new URL("..", import.meta.url),
    env: {
      ...process.env,
      ONEIROI_WEB_DIST: temporaryRoot,
      ONEIROI_WEB_HOST: "127.0.0.1",
      ONEIROI_WEB_PORT: String(originPort),
      ONEIROI_BFF_TARGET: `http://127.0.0.1:${upstreamPort}`,
      ONEIROI_WEB_PROXY_MAX_BODY_BYTES: "4096",
    },
    stdio: "ignore",
  });

  try {
    const baseUrl = `http://127.0.0.1:${originPort}`;
    await waitForOrigin(baseUrl, child);

    const form = new FormData();
    form.append("file", new Blob(["first-frame-bytes"], { type: "image/png" }), "head.png");
    form.append("title", "LAN upload");
    const upload = await fetch(`${baseUrl}/v1/uploads/images`, {
      method: "POST",
      body: form,
    });
    assert.equal(upload.status, 201);
    const uploadBody = await upload.json();
    assert.match(uploadBody.contentType, /^multipart\/form-data; boundary=/);
    assert.match(uploadBody.body, /filename="head.png"/);
    assert.match(uploadBody.body, /first-frame-bytes/);

    const boundary = "oneiroi-continue-boundary";
    const continueBody = Buffer.from(
      `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="continue.png"\r\nContent-Type: image/png\r\n\r\ncontinued-frame-bytes\r\n--${boundary}--\r\n`,
    );
    const continued = await postWithContinue(
      `${baseUrl}/v1/uploads/images`,
      `multipart/form-data; boundary=${boundary}`,
      continueBody,
    );
    assert.equal(continued.status, 201);
    assert.match(continued.body.toString("utf8"), /continued-frame-bytes/);

    const oversized = await fetch(`${baseUrl}/v1/conversations`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: Buffer.alloc(8192),
    });
    assert.equal(oversized.status, 413);
    assert.deepEqual(await oversized.json(), { detail: "REQUEST_TOO_LARGE" });

    const range = await fetch(`${baseUrl}/v1/jobs/job-test/file`, {
      headers: { Range: "bytes=0-9" },
    });
    assert.equal(range.status, 206);
    assert.equal(range.headers.get("content-range"), "bytes 0-9/10");
    assert.equal(await range.text(), "0123456789");
  } finally {
    await stop(child);
    await new Promise((resolve) => upstream.close(resolve));
    await rm(temporaryRoot, { recursive: true, force: true });
  }
});
