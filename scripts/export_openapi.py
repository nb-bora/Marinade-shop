"""Exporte le contrat OpenAPI de l'API, d'où le front génère ses types.

    python -m scripts.export_openapi ..\\Marinade-web\\api\\openapi.json

Sans argument, écrit sur la sortie standard.
"""

import json
import sys

from app.main import app


def main() -> int:
    document = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as handle:
            handle.write(document + "\n")
    else:
        print(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
