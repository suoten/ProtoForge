import { readFileSync, readdirSync, statSync } from "fs";
import { join, extname, relative } from "path";

interface OpenAPIPath {
  [method: string]: {
    operationId?: string;
    summary?: string;
    tags?: string[];
  };
}

interface OpenAPISpec {
  paths: Record<string, OpenAPIPath>;
  info?: { title?: string; version?: string };
}

interface ValidationError {
  file: string;
  line: number;
  method: string;
  endpoint: string;
  message: string;
}

function loadOpenAPISpec(specPath: string): OpenAPISpec {
  const raw = readFileSync(specPath, "utf-8");
  return JSON.parse(raw) as OpenAPISpec;
}

function buildEndpointSet(spec: OpenAPISpec): Set<string> {
  const endpoints = new Set<string>();
  for (const [path, methods] of Object.entries(spec.paths)) {
    for (const method of Object.keys(methods)) {
      endpoints.add(`${method.toUpperCase()} ${path}`);
    }
  }
  return endpoints;
}

function collectFiles(dir: string, extensions: string[]): string[] {
  const results: string[] = [];
  function walk(current: string) {
    const entries = readdirSync(current);
    for (const entry of entries) {
      const full = join(current, entry);
      const stat = statSync(full);
      if (stat.isDirectory()) {
        if (entry !== "node_modules" && entry !== "dist" && entry !== ".git") {
          walk(full);
        }
      } else if (extensions.includes(extname(entry))) {
        results.push(full);
      }
    }
  }
  walk(dir);
  return results;
}

const API_CALL_REGEX =
  /api\.(get|post|put|delete|patch|request)\s*\(\s*[`'"]([^`'"]+)[`'"]/g;

function extractApiCalls(
  content: string,
  filePath: string
): { method: string; endpoint: string; line: number }[] {
  const calls: { method: string; endpoint: string; line: number }[] = [];
  const lines = content.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let match: RegExpExecArray | null;
    const regex = new RegExp(API_CALL_REGEX.source, "g");
    while ((match = regex.exec(line)) !== null) {
      let method = match[1].toUpperCase();
      const rawPath = match[2];
      if (method === "REQUEST") {
        if (line.includes("method: 'DELETE'") || line.includes('method: "DELETE"')) {
          method = "DELETE";
        } else if (line.includes("method: 'PUT'") || line.includes('method: "PUT"')) {
          method = "PUT";
        } else if (line.includes("method: 'PATCH'") || line.includes('method: "PATCH"')) {
          method = "PATCH";
        } else if (line.includes("method: 'POST'") || line.includes('method: "POST"')) {
          method = "POST";
        } else {
          method = "GET";
        }
      }
      calls.push({ method, endpoint: rawPath, line: i + 1 });
    }
  }
  return calls;
}

function resolveEndpoint(basePath: string, rawPath: string): string {
  let resolved = rawPath;
  if (!resolved.startsWith("/")) {
    resolved = basePath + "/" + resolved;
  }
  resolved = resolved.replace(/\/+/g, "/");
  return resolved;
}

function main(): void {
  const projectRoot = join(__dirname, "..", "..");
  const specPath = join(projectRoot, "openapi.json");
  const webSrcDir = join(__dirname, "..", "src");

  let spec: OpenAPISpec;
  try {
    spec = loadOpenAPISpec(specPath);
  } catch (e) {
    console.error(`Failed to load openapi.json from ${specPath}: ${(e as Error).message}`);
    process.exit(1);
  }

  const backendEndpoints = buildEndpointSet(spec);
  const basePath = "/api/v1";

  const files = collectFiles(webSrcDir, [".vue", ".ts", ".js"]);
  const errors: ValidationError[] = [];
  const warnings: ValidationError[] = [];

  console.log(`\n=== ProtoForge API Consistency Check ===\n`);
  console.log(`OpenAPI spec: ${specPath}`);
  console.log(`Backend endpoints: ${backendEndpoints.size}`);
  console.log(`Frontend files to scan: ${files.length}\n`);

  for (const file of files) {
    const content = readFileSync(file, "utf-8");
    const calls = extractApiCalls(content, file);
    const relPath = relative(projectRoot, file);

    for (const call of calls) {
      const resolved = resolveEndpoint(basePath, call.endpoint);
      const lookupKey = `${call.method} ${resolved}`;
      const lookupKeyNoTrailing = lookupKey.replace(/\/$/, "");

      const found =
        backendEndpoints.has(lookupKey) ||
        backendEndpoints.has(lookupKeyNoTrailing) ||
        Array.from(backendEndpoints).some(
          (ep) =>
            ep === lookupKey ||
            ep === lookupKeyNoTrailing ||
            matchWithParams(ep, lookupKey)
        );

      if (!found) {
        errors.push({
          file: relPath,
          line: call.line,
          method: call.method,
          endpoint: resolved,
          message: `Endpoint ${call.method} ${resolved} not found in OpenAPI spec`,
        });
      }
    }
  }

  if (errors.length > 0) {
    console.error(`\n❌ Found ${errors.length} inconsistent API call(s):\n`);
    for (const err of errors) {
      console.error(`  ${err.file}:${err.line} - ${err.message}`);
    }
    console.error(
      `\nPlease ensure frontend API calls match the backend OpenAPI spec.`
    );
    console.error(
      `Run "python scripts/export-openapi.py" to regenerate openapi.json.\n`
    );
    process.exit(1);
  } else {
    console.log(`✅ All frontend API calls are consistent with backend OpenAPI spec.\n`);
  }
}

function matchWithParams(specEndpoint: string, lookupEndpoint: string): boolean {
  const specParts = specEndpoint.split(" ");
  const lookupParts = lookupEndpoint.split(" ");
  if (specParts.length !== 2 || lookupParts.length !== 2) return false;
  if (specParts[0] !== lookupParts[0]) return false;

  const specSegments = specParts[1].split("/");
  const lookupSegments = lookupParts[1].split("/");
  if (specSegments.length !== lookupSegments.length) return false;

  for (let i = 0; i < specSegments.length; i++) {
    if (specSegments[i].startsWith("{") && specSegments[i].endsWith("}")) {
      continue;
    }
    if (specSegments[i] !== lookupSegments[i]) return false;
  }
  return true;
}

main();
