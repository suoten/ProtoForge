import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from protoforge.main import create_app


def main():
    app = create_app()
    openapi_schema = app.openapi()
    output_path = Path(__file__).resolve().parent.parent / "openapi.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2, ensure_ascii=False)
    print(f"OpenAPI schema exported to {output_path}")
    paths_count = len(openapi_schema.get("paths", {}))
    print(f"Total API paths: {paths_count}")


if __name__ == "__main__":
    main()
