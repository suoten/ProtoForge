// Zero-dependency static file server for ZCode Sites packages.
// Usage: node static-server.mjs <site-dir>
// Env: PORT (default 3000), SPA_FALLBACK=1 to answer unknown extensionless paths with index.html.
// Listens on 0.0.0.0 so the runtime health check can reach it.
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";

const root = resolve(process.argv[2] ?? "dist");
const port = Number(process.env.PORT ?? 3000);
const spaFallback = process.env.SPA_FALLBACK === "1";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".htm": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "application/xml; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".avif": "image/avif",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
  ".wasm": "application/wasm",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".pdf": "application/pdf",
};

async function fileAt(path) {
  try {
    const info = await stat(path);
    return info.isFile() ? { path, size: info.size } : undefined;
  } catch {
    return undefined;
  }
}

// /about → about, about.html, about/index.html (covers static exports of Next, Astro, Hugo…).
async function resolveFile(urlPath) {
  const rel = normalize(decodeURIComponent(urlPath)).replace(/^([/\\])+/, "");
  const base = join(root, rel);
  if (base !== root && !base.startsWith(root + sep)) return undefined;
  return (
    (await fileAt(base)) ??
    (await fileAt(`${base}.html`)) ??
    (await fileAt(join(base, "index.html")))
  );
}

function send(req, res, status, file) {
  const type = MIME[extname(file.path).toLowerCase()] ?? "application/octet-stream";
  // Only the hashed-asset directories of common bundlers are cached forever (Vite/Rollup `assets/`,
  // Astro `_astro/`, Next `_next/static/`, CRA `static/{js,css,media}/`). Everything else, HTML
  // in particular, is revalidated so a redeploy shows up immediately.
  const rel = file.path.slice(root.length).split(sep).join("/");
  const immutable =
    !type.startsWith("text/html") &&
    /^\/(assets|_astro|_next\/static|static\/(js|css|media))\//.test(rel);
  res.writeHead(status, {
    "Content-Type": type,
    "Content-Length": file.size,
    "Cache-Control": immutable ? "public, max-age=31536000, immutable" : "no-cache",
  });
  if (req.method === "HEAD") return res.end();
  createReadStream(file.path).pipe(res);
}

createServer(async (req, res) => {
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405, { Allow: "GET, HEAD" }).end();
    return;
  }
  let pathname;
  try {
    pathname = new URL(req.url ?? "/", "http://localhost").pathname;
    decodeURIComponent(pathname);
  } catch {
    res.writeHead(400).end();
    return;
  }
  const file = await resolveFile(pathname);
  if (file) return send(req, res, 200, file);
  if (spaFallback && !extname(pathname)) {
    const index = await fileAt(join(root, "index.html"));
    if (index) return send(req, res, 200, index);
  }
  const notFound = await fileAt(join(root, "404.html"));
  if (notFound) return send(req, res, 404, notFound);
  res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" }).end("Not Found");
}).listen(port, "0.0.0.0", () => {
  console.log(
    `static-server: serving ${root} on 0.0.0.0:${port}${spaFallback ? " (SPA fallback)" : ""}`,
  );
});
