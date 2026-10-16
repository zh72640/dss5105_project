"""Direct Gemini SDK probe was retired with app.core.providers.

Use Chat v2 llm mode or ModelRegistry for live checks instead.
"""
import json
import sys


def main():
    result = {
        "diagnosis": "RETIRED",
        "error": "app.core.providers.llm_client was removed; use Chat v2 / ModelRegistry.",
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
