"""Write the OpenAPI schema to a file, for frontend type generation."""
import json
import sys
from pathlib import Path

# scripts/ sits one level below the backend package root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from main import app

out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
out.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
print(f"wrote {out}", file=sys.stderr)
