"""Opt-in live DeepSeek regression; public fixture data and a temporary database."""
import argparse
from dataclasses import replace
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config.model_settings import load_model_settings
from app.db.database import Database
from app.llm.registry import ModelRegistry
from app.services.chat import service as chat


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    settings = load_model_settings(mode='llm', legacy_backend='deepseek')
    spec = next(m for m in settings.models if m.provider == 'deepseek' and m.configured)
    registry = ModelRegistry(replace(settings, models=(spec,), default_model=spec.key))
    report = {'provider':spec.provider, 'model':spec.api_model_id, 'steps':[], 'production_database_touched':False}
    try:
        with tempfile.TemporaryDirectory(prefix='sweaterco-live-regression-') as folder:
            db = str(Path(folder)/'fixture.sqlite3')
            sid = chat.create(owner='live-regression', request_id='create', db_path=db,
                as_of=date(2026,4,1), mode='llm', model_key=spec.key, registry=registry)['session_id']
            def turn(key, text='', **extra):
                current = chat.inspect(sid, owner='live-regression', db_path=db)
                started = time.monotonic()
                retries = []
                for attempt in range(2):
                    try:
                        result = chat.turn(sid, owner='live-regression', request_id=key,
                            expected_version=current['version'], db_path=db, message=text, registry=registry, **extra)
                        break
                    except chat.ChatError as error:
                        retries.append({'code':error.code,'details':error.details})
                        if not (error.details or {}).get('retryable') or attempt:
                            report['failed_turn'] = {'key':key,'errors':retries}
                            raise
                item = {'key':key, 'message':text, 'state':result['session']['task']['state'],
                    'draft':result['session']['task']['draft'], 'seconds':round(time.monotonic()-started,2),
                    'reply':result['assistant_message']['content'], 'committed':result['committed'], 'retries':retries}
                report['steps'].append(item)
                print(json.dumps({k:item[k] for k in ('key','state','seconds','committed')}), flush=True)
                return result
            first = turn('suspended', 'Allocate ORD-041 to W7 only. Exclude W6.')
            assert first['task_state'] == 'BLOCKED'
            second = turn('clear', 'Clear preferred workshop. Use weighted_hybrid (normalized 80/20).')
            draft = second['session']['task']['draft']
            assert second['task_state'] == 'RECOMMENDED'
            assert draft['preferred_workshop'] is None and draft['exclusion'] == ['W6']
            assert draft['objective'] == 'weighted_hybrid'
            third = turn('add', 'Also exclude BudgetWorks.')
            assert third['session']['task']['draft']['exclusion'] == ['W3','W6']
            fourth = turn('remove', 'Do not exclude BudgetWorks anymore.')
            assert fourth['session']['task']['draft']['exclusion'] == ['W6']
            with Database(db) as database:
                assert database.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0] == 0
            confirmed = turn('confirm', action='confirm', recommendation_id=fourth['recommendation_id'])
            assert confirmed['committed'] and confirmed['task_state'] == 'CONFIRMED'
            report['explanation_fallbacks'] = sum(e['event_type'] == 'explanation_fallback'
                for e in chat.execution_trace(sid, owner='live-regression', db_path=db)['events'])
            report['status'] = 'PASS'
    except Exception as error:
        report.update(status='FAIL', error_type=type(error).__name__, error_code=getattr(error,'code',None))
    finally:
        registry.close()
        report['checked_at'] = datetime.now(timezone.utc).isoformat()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps({'status':report['status'],'output':str(args.output)}), flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
