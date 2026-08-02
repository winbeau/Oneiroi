import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, resolve, sep } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

const root = resolve(process.env.ONEIROI_WEB_DIST ?? "apps/web/dist");
const bffTarget = new URL(process.env.ONEIROI_BFF_TARGET ?? "http://127.0.0.1:8000");
const host = process.env.ONEIROI_WEB_HOST ?? "127.0.0.1";
const port = Number(process.env.ONEIROI_WEB_PORT ?? 4173);
const proxyMaxBodyBytes = Number(
  process.env.ONEIROI_WEB_PROXY_MAX_BODY_BYTES ?? 20 * 1024 * 1024,
);

class RequestBodyTooLargeError extends Error {}

const MIME_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".gif": "image/gif",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};
const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function isApiPath(pathname) {
  return pathname === "/healthz" || pathname === "/v1" || pathname.startsWith("/v1/");
}

function copyRequestHeaders(request) {
  const headers = new Headers();
  for (const [name, value] of Object.entries(request.headers)) {
    const normalized = name.toLowerCase();
    if (
      !HOP_BY_HOP_HEADERS.has(normalized) &&
      normalized !== "content-length" &&
      normalized !== "host" &&
      value !== undefined
    ) {
      headers.set(name, value);
    }
  }
  return headers;
}

function copyResponseHeaders(response) {
  const headers = {};
  for (const [name, value] of response.headers) {
    if (!HOP_BY_HOP_HEADERS.has(name.toLowerCase())) {
      headers[name] = value;
    }
  }
  return headers;
}

async function readRequestBody(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > proxyMaxBodyBytes) {
      throw new RequestBodyTooLargeError();
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks, size);
}

async function proxyApi(request, response, requestUrl) {
  const target = new URL(requestUrl.pathname + requestUrl.search, bffTarget);
  const hasBody = !["GET", "HEAD"].includes(request.method ?? "GET");
  const body = hasBody ? await readRequestBody(request) : undefined;
  const abortController = new AbortController();
  request.once("aborted", () => abortController.abort());
  response.once("close", () => {
    if (!response.writableEnded) abortController.abort();
  });
  const upstream = await fetch(target, {
    method: request.method,
    headers: copyRequestHeaders(request),
    body,
    redirect: "manual",
    signal: abortController.signal,
  });
  response.writeHead(upstream.status, copyResponseHeaders(upstream));
  if (request.method === "HEAD" || !upstream.body) {
    response.end();
    return;
  }
  await pipeline(Readable.fromWeb(upstream.body), response);
}

async function serveStatic(request, response, requestUrl) {
  let requestedPath;
  try {
    requestedPath = decodeURIComponent(requestUrl.pathname);
  } catch {
    response.writeHead(400);
    response.end("Bad Request");
    return;
  }
  const candidate = resolve(root, `.${requestedPath}`);
  if (candidate !== root && !candidate.startsWith(`${root}${sep}`)) {
    response.writeHead(400);
    response.end("Bad Request");
    return;
  }

  let file = candidate;
  let fileStat;
  try {
    fileStat = await stat(file);
    if (!fileStat.isFile()) throw new Error("not a file");
  } catch {
    if (requestedPath.startsWith("/assets/")) {
      response.writeHead(404);
      response.end("Not Found");
      return;
    }
    file = resolve(root, "index.html");
    fileStat = await stat(file);
  }

  const headers = {
    "Cache-Control": requestedPath.startsWith("/assets/")
      ? "public, max-age=31536000, immutable"
      : "no-cache",
    "Content-Length": fileStat.size,
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    "Content-Type": MIME_TYPES[extname(file).toLowerCase()] ?? "application/octet-stream",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
  };
  response.writeHead(200, headers);
  if (request.method === "HEAD") {
    response.end();
    return;
  }
  await pipeline(createReadStream(file), response);
}

const server = createServer(async (request, response) => {
  try {
    const requestUrl = new URL(request.url ?? "/", `http://${request.headers.host ?? "localhost"}`);
    if (isApiPath(requestUrl.pathname)) {
      await proxyApi(request, response, requestUrl);
      return;
    }
    await serveStatic(request, response, requestUrl);
  } catch (error) {
    if (!response.headersSent) {
      const bodyTooLarge = error instanceof RequestBodyTooLargeError;
      response.writeHead(bodyTooLarge ? 413 : 502, {
        "Content-Type": "application/json",
      });
      response.end(
        JSON.stringify({
          detail: bodyTooLarge ? "REQUEST_TOO_LARGE" : "UPSTREAM_ORIGIN_UNAVAILABLE",
        }),
      );
    } else if (!response.destroyed) {
      response.destroy();
    }
    console.error(error instanceof Error ? error.message : error);
  }
});

server.listen(port, host, () => {
  console.log(`Oneiroi static origin listening on http://${host}:${port}`);
});

const shutdown = () => server.close(() => process.exit(0));
process.once("SIGTERM", shutdown);
process.once("SIGINT", shutdown);
