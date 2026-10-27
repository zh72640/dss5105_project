"""Opt-in real DeepSeek smoke check using the startup environment; never log keys."""
import json
import argparse
import re
import sys
import tempfile
from datetime import date, datetime, timezone
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.model_settings import load_model_settings
from app.llm.errors import check_response, text_content, translate_error
from app.llm.registry import ModelRegistry


def workflow(registry, spec, output):
    from app.db.database import Database
    from app.services.chat import service as chat
    from app.services.allocation.contracts import saved_result

    report = {"status": "RUNNING", "provider": "deepseek", "model": spec.api_model_id,
              "mode": "llm", "production_database_touched": False, "cases": []}
    try:
        with tempfile.TemporaryDirectory(prefix="sweaterco-deepseek-") as folder:
            db = str(Path(folder) / "live.sqlite3")
            for index, (order, objective, message) in enumerate([
                ("ORD-045", "weighted_hybrid", "Allocate ORD-045 using weighted hybrid (80% lateness and 20% defect exposure) to one workshop."),
                ("ORD-041", "min_cost", "Allocate ORD-041 at the lowest cost to one workshop."),
            ]):
                print(json.dumps({"stage": "workflow_started", "objective": objective}), flush=True)
                sid = chat.create(owner="live-check", request_id=f"create-{index}", db_path=db,
                    as_of=date(2026, 4, 1), mode="llm", model_key=spec.key, registry=registry)["session_id"]
                response = chat.turn(sid, owner="live-check", request_id=f"plan-{index}",
                    expected_version=0, db_path=db, message=message, registry=registry)
                session = chat.inspect(sid, owner="live-check", db_path=db)
                rec = session["recommendation"]
                trace = chat.execution_trace(sid, owner="live-check", db_path=db)
                calls = [event["detail"] for event in trace["events"] if event["event_type"] == "model_call"]
                case = {"order_id": order, "objective": objective, "live_model_calls": len(calls),
                        "stages": [call["stage"] for call in calls],
                        "allocation": response.get("allocation"), "explanation": response.get("explanation")}
                report["cases"].append(case)
                assert rec and rec["status"] == "valid", response.get("explanation", "No recommendation")
                assert response["allocation"] == saved_result(rec)
                assert response["allocation"]["objective"] == objective
                assert not response["committed"]
                explanation = response["explanation"]
                headings = ["Allocation plan", "Allocation method", "Why this recommendation", "Review before allocation"]
                matches = [re.search(r"(?:^|\n)[#*\s]*" + heading, explanation, re.I) for heading in headings]
                assert all(matches), "The explanation did not include all four requested sections."
                positions = [match.start() for match in matches]
                assert positions == sorted(positions)
                assert order in explanation and response["allocation"]["workshop_name"] in explanation
                assert response["allocation"]["explanation_evidence"]["candidates"]
                with Database(db) as database:
                    assert database.connection.execute("SELECT state FROM orders WHERE order_id=?", (order,)).fetchone()[0] != "WORKING"
                assert calls[-1]["stage"] == "explanation"
                assert calls[-1]["prompt"]["version"] == "v3"
                confirmation = dict(owner="live-check", request_id=f"confirm-{index}", db_path=db,
                                    expected_version=session["version"], action="confirm",
                                    recommendation_id=rec["recommendation_id"], registry=registry)
                committed = chat.turn(sid, **confirmation)
                replay = chat.turn(sid, **confirmation)
                assert committed["committed"] and replay["committed"] and replay["replayed"]
                case["explicit_confirmation_and_replay"] = "PASS"
            report["status"] = "PASS"
    except Exception as error:
        report.update(status="FAIL", error_type=type(error).__name__,
                      error_code=getattr(error, "code", type(error).__name__))
        details = getattr(error, "details", {}) or {}
        report["model_error"] = details.get("model_error")
        report["phase"] = details.get("phase")
        if isinstance(error, (AssertionError, ValueError)):
            report["check_failure"] = str(error)[:2000]
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"} | {
        "report": str(output), "cases": len(report["cases"]),
        "live_model_calls": sum(case["live_model_calls"] for case in report["cases"])}), flush=True)
    return 0 if report["status"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", action="store_true", help="Exercise real extraction, tools, explanation and explicit confirmation on temporary data.")
    parser.add_argument("--output", type=Path, default=Path("evaluation/live_results/deepseek-workflow.json"))
    args = parser.parse_args()
    settings = load_model_settings(mode="llm", legacy_backend="deepseek")
    spec = next((s for s in settings.models if s.provider == "deepseek" and s.configured), None)
    if spec is None:
        print(json.dumps({"status": "NOT_CONFIGURED", "credential_present": False}))
        return 2
    # Only contact DeepSeek, even if other providers are present in the shell.
    settings = replace(settings, default_model=spec.key, models=(spec,))
    registry = ModelRegistry(settings)
    try:
        if args.workflow:
            return workflow(registry, spec, args.output)
        model = registry.get_model("llm", spec.key)
        reply = model.invoke([("human", "Reply with exactly DEEPSEEK_OK.")])
        check_response(reply)
        matched = text_content(reply).strip() == "DEEPSEEK_OK"
        print(json.dumps({"status": "PASS" if matched else "UNEXPECTED_REPLY",
                          "credential_present": True, "provider": "deepseek",
                          "model": spec.api_model_id, "live_model_calls": 1,
                          "response_matches": matched,
                          "usage": getattr(reply, "usage_metadata", None)}))
        return 0 if matched else 1
    except Exception as error:
        translated = translate_error(error, "deepseek")
        print(json.dumps({"status": "FAIL", "error_type": type(error).__name__,
                          "code": getattr(translated, "code", str(translated)), "provider": "deepseek",
                          "model": spec.api_model_id}))
        return 1
    finally:
        registry.close()


if __name__ == "__main__":
    raise SystemExit(main())
