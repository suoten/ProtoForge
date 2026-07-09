"""Layer 2: Frontend API <-> Backend OpenAPI Schema Cross-Check.

This script:
1. Starts the FastAPI app and exports the OpenAPI schema
2. Parses the frontend api.js to extract all API endpoint calls
3. Compares the two to find mismatches (missing endpoints, wrong methods, etc.)
4. Optionally generates TypeScript types from OpenAPI and compares with existing types

Usage:
    python scripts/audit_api_types.py [--app-url URL] [--web-dir PATH] [--strict]

Can be run standalone or as part of CI.
"""

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse


@dataclass
class ApiMismatch:
    """A single API endpoint mismatch."""

    source: str  # "frontend" or "backend"
    method: str
    path: str
    mismatch_type: str  # "not_in_backend" | "not_in_frontend" | "method_mismatch"
    detail: str = ""


@dataclass
class ApiAuditResult:
    """Result of an API consistency audit."""

    mismatches: list[ApiMismatch] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    backend_endpoints: int = 0
    frontend_endpoints: int = 0

    @property
    def ok(self) -> bool:
        return len(self.mismatches) == 0

    def summary(self) -> str:
        lines = [
            f"API Consistency Audit: {self.backend_endpoints} backend, {self.frontend_endpoints} frontend endpoints",
        ]
        if self.ok:
            lines.append("All frontend API calls match backend OpenAPI spec.")
        else:
            lines.append(f"Found {len(self.mismatches)} mismatch(es):")
            for m in self.mismatches:
                lines.append(f"  [{m.mismatch_type}] {m.method} {m.path} ({m.source}): {m.detail}")
        for w in self.warnings:
            lines.append(f"  [warning] {w}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Frontend API parser - extracts endpoints from api.js
# ---------------------------------------------------------------------------

# Regex to match api.get/post/put/delete calls with string literal paths
_API_CALL_PATTERN = re.compile(
    r"(?:api|axios)\.(get|post|put|delete|patch)\s*\(\s*[`'\"]([^`'\"]+)[`'\"]",
    re.MULTILINE,
)

# Regex to match template literal paths with interpolation
_TEMPLATE_LITERAL_PATTERN = re.compile(
    r"api\.(get|post|put|delete|patch)\s*\(\s*[`'](/[^`']*?\$\{[^}]+\}[^`']*?)[`']",
    re.MULTILINE,
)


def parse_frontend_api(api_js_path: Path, base_path: str = "/api/v1") -> list[tuple[str, str, int]]:
    """Parse frontend api.js to extract (method, path, line_number) tuples.

    The frontend api.js uses axios with baseURL='/api/v1', so paths like
    '/auth/login' in the source correspond to '/api/v1/auth/login' in the
    OpenAPI spec. We prepend the base_path to get the full path.
    """
    if not api_js_path.exists():
        return []

    content = api_js_path.read_text(encoding="utf-8")
    endpoints = []

    for i, line in enumerate(content.splitlines(), 1):
        for match in _API_CALL_PATTERN.finditer(line):
            method = match.group(1).upper()
            raw_path = match.group(2)
            # Resolve relative paths
            if not raw_path.startswith("/"):
                raw_path = "/" + raw_path
            # Prepend base_path only if not already present
            if raw_path.startswith(base_path):
                full_path = raw_path
            else:
                full_path = base_path + raw_path
            # Normalize path (remove duplicate slashes)
            full_path = full_path.replace("//", "/")
            # Convert template literals like /devices/${id} to /devices/{id}
            normalized = re.sub(r"\$\{[^}]+\}", "{id}", full_path)
            endpoints.append((method, normalized, i))

    return endpoints


# ---------------------------------------------------------------------------
# OpenAPI spec parser
# ---------------------------------------------------------------------------


def parse_openapi_spec(spec: dict[str, Any]) -> set[tuple[str, str]]:
    """Parse OpenAPI spec to extract set of (method, path) tuples."""
    endpoints = set()
    paths = spec.get("paths", {})
    for path, methods in paths.items():
        for method in methods:
            if method.lower() in ("get", "post", "put", "delete", "patch"):
                endpoints.add((method.upper(), path))
    return endpoints


def load_openapi_from_file(openapi_path: Path) -> Optional[dict[str, Any]]:
    """Load OpenAPI spec from a JSON file."""
    if not openapi_path.exists():
        return None
    try:
        return json.loads(openapi_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Failed to load OpenAPI spec from {openapi_path}: {e}")
        return None


def fetch_openapi_from_app(app_url: str) -> Optional[dict[str, Any]]:
    """Fetch OpenAPI spec from a running FastAPI app."""
    try:
        import httpx
        response = httpx.get(f"{app_url}/openapi.json", timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Warning: Failed to fetch OpenAPI spec from {app_url}: {e}")
        return None


def export_openapi_from_app() -> Optional[dict[str, Any]]:
    """Export OpenAPI spec by importing the FastAPI app directly."""
    try:
        from protoforge.main import app
        return app.openapi()
    except Exception as e:
        print(f"Warning: Failed to export OpenAPI spec from app: {e}")
        return None


# ---------------------------------------------------------------------------
# Path matching (handle path parameters)
# ---------------------------------------------------------------------------


def normalize_path_for_comparison(path: str) -> str:
    """Normalize a path for comparison.

    Converts template literals and path parameters to a common format:
    /devices/{id}/points/{point} -> /devices/_/points/_
    """
    # Replace {param} and ${param} with placeholder
    result = re.sub(r"\{[^}]+\}", "_", path)
    result = re.sub(r"\$\{[^}]+\}", "_", result)
    # Remove trailing slashes
    result = result.rstrip("/")
    return result


def paths_match(frontend_path: str, backend_path: str) -> bool:
    """Check if a frontend path matches a backend path (with parameter wildcards)."""
    return normalize_path_for_comparison(frontend_path) == normalize_path_for_comparison(backend_path)


# ---------------------------------------------------------------------------
# Main audit logic
# ---------------------------------------------------------------------------


def audit_api_consistency(
    openapi_spec: dict[str, Any],
    frontend_endpoints: list[tuple[str, str, int]],
    strict: bool = False,
) -> ApiAuditResult:
    """Compare frontend API calls against backend OpenAPI spec.

    Args:
        openapi_spec: Parsed OpenAPI specification dict.
        frontend_endpoints: List of (method, path, line_number) from frontend.
        strict: If True, treat warnings as errors.

    Returns:
        ApiAuditResult with any mismatches found.
    """
    result = ApiAuditResult()

    backend_endpoints = parse_openapi_spec(openapi_spec)
    result.backend_endpoints = len(backend_endpoints)
    result.frontend_endpoints = len(frontend_endpoints)

    # Build a lookup set for backend endpoints (normalized)
    backend_normalized = {
        (method, normalize_path_for_comparison(path)): path
        for method, path in backend_endpoints
    }

    # Check each frontend endpoint against backend
    matched_backend = set()
    for method, path, line_num in frontend_endpoints:
        normalized = normalize_path_for_comparison(path)

        # Try exact match first
        if (method, path.rstrip("/")) in backend_endpoints or (method, path) in backend_endpoints:
            matched_backend.add((method, path.rstrip("/")))
            matched_backend.add((method, path))
            continue

        # Try normalized match (with parameter wildcards)
        if (method, normalized) in backend_normalized:
            matched_backend.add((method, normalized))
            continue

        # No match found
        result.mismatches.append(ApiMismatch(
            source="frontend",
            method=method,
            path=path,
            mismatch_type="not_in_backend",
            detail=f"Frontend calls {method} {path} (line {line_num}) but no matching backend endpoint exists",
        ))

    # Check for backend endpoints not called from frontend (informational)
    if strict:
        frontend_set = {(method, normalize_path_for_comparison(path)) for method, path, _ in frontend_endpoints}
        for method, path in backend_endpoints:
            normalized = normalize_path_for_comparison(path)
            if (method, normalized) not in frontend_set:
                result.warnings.append(
                    f"Backend endpoint {method} {path} not called from frontend api.js"
                )

    return result


# ---------------------------------------------------------------------------
# TypeScript type generation check
# ---------------------------------------------------------------------------


def check_typescript_types(web_dir: Path) -> list[str]:
    """Check if TypeScript types are generated and up-to-date.

    Returns list of warning messages.
    """
    warnings = []
    api_types_path = web_dir / "src" / "api-types.d.ts"

    if not api_types_path.exists():
        warnings.append(
            f"TypeScript types file not found: {api_types_path}. "
            f"Run 'npm run generate-types' in web/ to generate it."
        )
    else:
        # Check if the file is recent (within last 7 days)
        import time
        mtime = api_types_path.stat().st_mtime
        age_days = (time.time() - mtime) / 86400
        if age_days > 7:
            warnings.append(
                f"TypeScript types file is {age_days:.0f} days old. "
                f"Consider regenerating with 'npm run generate-types'."
            )

    return warnings


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ProtoForge API Consistency Audit - Layer 2",
    )
    parser.add_argument(
        "--app-url",
        default="",
        help="URL of running ProtoForge app to fetch OpenAPI spec from",
    )
    parser.add_argument(
        "--openapi-file",
        default="",
        help="Path to openapi.json file (alternative to --app-url)",
    )
    parser.add_argument(
        "--web-dir",
        default="web",
        help="Path to web/ directory (default: web)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (e.g., backend endpoints not called from frontend)",
    )
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent

    # 1. Load OpenAPI spec
    openapi_spec = None
    if args.openapi_file:
        openapi_spec = load_openapi_from_file(Path(args.openapi_file))
    elif args.app_url:
        openapi_spec = fetch_openapi_from_app(args.app_url)

    if openapi_spec is None:
        # Try loading from project root
        openapi_spec = load_openapi_from_file(project_root / "openapi.json")

    if openapi_spec is None:
        # Try importing app directly
        print("Attempting to export OpenAPI spec from app...")
        openapi_spec = export_openapi_from_app()

    if openapi_spec is None:
        print("ERROR: Could not obtain OpenAPI spec. Start the app or provide --openapi-file.")
        return 1

    # 2. Parse frontend API calls
    web_dir = Path(args.web_dir) if Path(args.web_dir).is_absolute() else project_root / args.web_dir
    api_js_path = web_dir / "src" / "api.js"
    frontend_endpoints = parse_frontend_api(api_js_path)

    if not frontend_endpoints:
        print(f"WARNING: No frontend API calls found in {api_js_path}")

    # 3. Run audit
    result = audit_api_consistency(openapi_spec, frontend_endpoints, strict=args.strict)

    # 4. Check TypeScript types
    ts_warnings = check_typescript_types(web_dir)
    result.warnings.extend(ts_warnings)

    # 5. Print results
    print("\n=== ProtoForge API Consistency Audit (Layer 2) ===\n")
    print(result.summary())

    if not result.ok:
        print("\nAction items:")
        print("  - For 'not_in_backend': Remove the frontend call or add the backend endpoint")
        print("  - For 'not_in_frontend': Consider if the endpoint is needed or add frontend support")
        print("  - Run 'npm run generate-types' in web/ to update TypeScript types")

    return 1 if (not result.ok or (args.strict and result.warnings)) else 0


if __name__ == "__main__":
    sys.exit(main())
