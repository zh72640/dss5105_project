"""Explicit live Gemini smoke via Chat LLM path; direct providers were removed."""
import argparse
import json
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.services.chat import service as chat
from app.config.model_settings import load_model_settings
from app.llm.registry import ModelRegistry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluation/live_results")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "provider": "gemini",
        "api_key_env": "GEMINI_API_KEY",
        "status": "NOT_RUN",
        "live_llm_validated": False,
        "note": "Uses Chat v2 llm mode via ModelRegistry; legacy LLMBackend was removed.",
    }
    if not os.getenv("GEMINI_API_KEY", "").strip():
        summary["reason"] = "gemini_api_key_missing"
    else:
        with tempfile.TemporaryDirectory(prefix="gemini-live-") as directory:
            path = str(Path(directory) / "live.sqlite3")
            settings = load_model_settings(legacy_backend='llm')
            model = next(spec for spec in settings.models if spec.provider == 'gemini' and spec.configured)
            summary['model_key'] = model.key
            registry = ModelRegistry(settings)
            try:
                created = chat.create(
                    owner="live", request_id="live-create", db_path=path,
                    as_of=date(2026, 4, 1), message="Allocate ORD-045 cheapest.", mode="llm",
                    model_key=model.key, registry=registry)
            except chat.ChatError as error:
                created = {'error': error.code, 'http_status': error.status, 'committed': False}
            finally:
                registry.close()
            ok = (created.get("session", {}).get("recommendation") is not None and
                  not created.get('committed') and created.get('http_status', 200) < 400)
            summary.update(
                status="SMOKE_PASSED" if ok else "SMOKE_FAILED",
                task_state=created.get("task_state"),
                session_id=created.get("session_id"))
            (args.output_dir / "gemini_chat_smoke.json").write_text(
                json.dumps(created, indent=2, ensure_ascii=False, default=str) + "\n")
    (args.output_dir / "gemini_live_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "SMOKE_PASSED" else 2 if summary["status"] == "NOT_RUN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
