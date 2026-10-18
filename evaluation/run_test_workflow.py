"""Run offline and mocked acceptance checks, preserving evidence for every run.

Each stage runs in a separate process. Failures do not suppress later stages.
Live model acceptance is deliberately excluded; no provider credentials are needed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STAGES = ('python', 'frontend', 'agent', 'language', 'http', 'simulator', 'browser')
# Historical labels expect DECLINE for these two requests. Chat v2 clarifies them.
# Keep them visible as warnings; do not change the labels or accept new mismatches.
KNOWN_LANGUAGE_DIFFERENCES = {'R02': 'CLARIFY', 'R13': 'CLARIFY'}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inspect_result(stage, output, log):
    warnings, details = [], {}
    if stage == 'python':
        match = re.search(r'Ran (\d+) tests? in', log)
        require(match and int(match[1]) > 0, 'No Python tests were executed.')
        details['tests'] = int(match[1])
        if 'ResourceWarning:' in log:
            warnings.append('Python emitted ResourceWarnings; see the log for unclosed test resources.')
        if 'skipped=' in log:
            warnings.append('Some Python tests were skipped; see the log.')
    elif stage == 'frontend':
        match = re.search(r'^# tests (\d+)$', log, re.MULTILINE)
        require(match and int(match[1]) > 0, 'No frontend tests were executed.')
        details['tests'] = int(match[1])
        if re.search(r'^# (?:skipped|todo) [1-9]', log, re.MULTILINE):
            warnings.append('Some frontend tests were skipped or marked TODO.')
    elif stage == 'agent':
        report = read_json(output / 'agent.json')
        details = {'transport': 'scripted mock', 'committed': report['allocation']['committed'],
                   'confirmation_replayed': report['allocation']['confirmation_replayed'],
                   'production_events': report['production']['event_count']}
        require(details['committed'] and details['confirmation_replayed'] and details['production_events'] == 1,
                'Native-tool confirmation, replay or production acceptance failed.')
    elif stage == 'language':
        summary = read_json(output / 'language/summary.json')
        cases = [json.loads(line) for line in (output / 'language/cases.jsonl').read_text().splitlines()]
        require(len(cases) == summary['cases'] == summary['service_successes'] == 30,
                'Expected 30 successful Offline service responses.')
        require(summary['mode'] == 'offline' and summary['production_rows_written'] == 0,
                'Language evaluation changed mode or committed production work.')
        differences = [{'id': row['id'], 'expected': row['expected_behavior'], 'actual': row['actual_behavior']}
                       for row in cases if not row['behavior_match']]
        details = {'cases': len(cases), 'matches': summary['behavior_matches'], 'differences': differences}
        unexpected = [row for row in differences
                      if row['expected'] != 'DECLINE' or KNOWN_LANGUAGE_DIFFERENCES.get(row['id']) != row['actual']]
        require(not unexpected, f'Unexpected language regressions: {unexpected}')
        if differences:
            warnings.append('Historical label differences remain: ' + ', '.join(row['id'] for row in differences)
                            + '. This is development data, not live-model accuracy.')
    elif stage == 'http':
        details = read_json(output / 'http.json')
        require(details['preview_count'] == 20 and details['confirmed_count'] == details['exported_decisions'] == 10,
                'Expected 20 previews, 10 confirmations and 10 matching audit exports.')
        require(details['all_observed_responses_under_3_seconds'] and not details['production_database_touched'],
                'Offline HTTP timing or database isolation check failed.')
    elif stage == 'simulator':
        report = read_json(output / 'simulator/simulator_comparison.json')
        baseline = read_json(ROOT / 'evaluation/results/scope_review_20261017/simulator-comparison.json')
        metrics = lambda data: {(row['seed'], row['scenario'], row['policy']): row['metrics'] for row in data['runs']}
        require(len(report['runs']) == 14 and all(row['metrics']['batches'] == 120 for row in report['runs']),
                'Expected 14 complete simulator configurations with 120 orders each.')
        require(metrics(report) == metrics(baseline), 'Simulator metrics differ from the reviewed baseline.')
        details = {'configurations': 14, 'orders_per_configuration': 120, 'baseline_metrics_match': True,
                   'scope': 'Fixed seed, development data, single-workshop adapter; no split-benefit claim.'}
    elif stage == 'browser':
        details = read_json(output / 'browser/browser.json')
        require(details['status'] == 'PASS' and len(details['checks']) == 4 and not details['page_errors'],
                'Browser acceptance did not complete all four checks.')
        require(details['operations']['status'] == 'PASS' and len(details['operations']['checks']) == 5
                and not details['operations']['page_errors'], 'Operations browser acceptance did not complete.')
    return details, warnings


def execute_stage(name, command, output, *, timeout, env):
    started = time.perf_counter()
    path = output / f'{name}.log'
    result = {'stage': name, 'status': 'FAIL', 'log': path.name, 'returncode': None, 'warnings': []}
    try:
        with path.open('w', encoding='utf-8') as stream:
            process = subprocess.run(command, cwd=ROOT, env=env, stdout=stream,
                                     stderr=subprocess.STDOUT, timeout=timeout, check=False)
        result['returncode'] = process.returncode
        require(process.returncode == 0, f'Process exited with code {process.returncode}; see {path.name}.')
        result['details'], result['warnings'] = inspect_result(name, output, path.read_text(errors='replace'))
        result['status'] = 'WARN' if result['warnings'] else 'PASS'
    except subprocess.TimeoutExpired:
        result['error'] = f'Stage exceeded {timeout} seconds; see {path.name}.'
    except (OSError, ValueError, KeyError, TypeError) as error:
        result['error'] = str(error)
    result['elapsed_seconds'] = round(time.perf_counter() - started, 2)
    return result


def write_report(output, report):
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    lines = ['# Offline test workflow', '', f"Status: **{report['status']}**", '',
             f"Started (UTC): {report['started_at']}", '',
             'Live model acceptance: **NOT RUN**. Provider transports are mocked or Offline mode is used.', '',
             '| Stage | Status | Seconds | Evidence |', '| --- | --- | ---: | --- |']
    for row in report['stages']:
        evidence = f"[{row['log']}]({row['log']})" if row.get('log') else 'Not requested'
        lines.append(f"| {row['stage']} | {row['status']} | {row.get('elapsed_seconds', '')} | {evidence} |")
    for row in report['stages']:
        for issue in [*row.get('warnings', []), *([row['error']] if row.get('error') else [])]:
            lines.extend(['', f"- {row['stage']}: {issue}"])
        if row.get('details'):
            lines.extend(['', f"## {row['stage']} details", '', '```json',
                          json.dumps(row['details'], indent=2), '```'])
    lines.extend(['', 'Browser screenshots, per-case language results, simulator outputs and the source manifest',
                  'are saved in this run directory. Local HTTP timing does not establish online-model latency.', ''])
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


def source_snapshot():
    paths = sorted(path for directory in ('app', 'tests', 'evaluation', 'harness', 'data')
                   for path in (ROOT / directory).rglob('*') if path.is_file()
                   and path.suffix in {'.py', '.cjs', '.js', '.css', '.html', '.md', '.yaml', '.csv', '.txt'}
                   and not {'__pycache__', 'results', 'live_results'}.intersection(path.relative_to(ROOT).parts))
    paths += [ROOT / 'pyproject.toml', ROOT / 'uv.lock']
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stages', nargs='+', choices=STAGES, default=list(STAGES))
    parser.add_argument('--output-dir', type=Path, help='New directory only; existing reports are never overwritten.')
    parser.add_argument('--browser-python', default=sys.executable, help='Python with Playwright and project dependencies.')
    parser.add_argument('--browser-executable', default=shutil.which('chromium') or shutil.which('google-chrome')
                        or '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    parser.add_argument('--timeout-seconds', type=int, default=300, help='Per-stage timeout.')
    args = parser.parse_args(argv)
    if args.timeout_seconds < 1:
        parser.error('--timeout-seconds must be positive')
    output = (args.output_dir or ROOT / 'evaluation/live_results' /
              datetime.now(timezone.utc).strftime('workflow-%Y%m%dT%H%M%S%fZ')).resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error('Output directory already exists; choose a new run directory.')
    # Keep credentials and host model-selection settings out of test subprocesses.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('OPENAI_', 'ANTHROPIC_', 'GEMINI_', 'DEEPSEEK_', 'LLM_', 'LANGCHAIN_', 'LANGSMITH_'))
           and key not in {'AGENT_MODE', 'PARSER_BACKEND', 'GOOGLE_API_KEY'}}
    env.update({'PYTHONUTF8': '1', 'PYTHONUNBUFFERED': '1', 'LANGCHAIN_TRACING_V2': 'false',
                'LANGSMITH_TRACING': 'false'})
    py = [sys.executable, '-X', 'utf8']
    commands = {
        'python': [*py, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-q'],
        'frontend': ['node', '--test', '--test-reporter=tap', *map(str, sorted((ROOT / 'tests').glob('*.cjs')))],
        'agent': [*py, '-m', 'evaluation.verify_dynamic_agent', '--output', str(output / 'agent.json')],
        'language': [*py, '-m', 'evaluation.evaluate_chat_language', '--mode', 'offline', '--output-dir', str(output / 'language')],
        'http': [*py, '-m', 'evaluation.verify_ui', '--output', str(output / 'http.json')],
        'simulator': [*py, '-m', 'evaluation.compare_simulator', '--output-dir', str(output / 'simulator')],
        'browser': [args.browser_python, '-X', 'utf8', 'evaluation/verify_scope_flow_browser.py',
                    '--executable', args.browser_executable, '--output-dir', str(output / 'browser')],
    }
    snapshot = source_snapshot()
    (output / 'source-manifest.json').write_text(json.dumps(snapshot, indent=2) + '\n', encoding='utf-8')
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'RUNNING',
              'live_model_acceptance': 'NOT_RUN', 'database_scope': 'Temporary test databases only',
              'stages': [{'stage': stage, 'status': 'PENDING' if stage in args.stages else 'NOT_RUN'} for stage in STAGES]}
    write_report(output, report)
    print(f'Evidence: {output}', flush=True)
    try:
        for index, name in enumerate(STAGES):
            if name not in args.stages:
                continue
            print(f'[{index + 1}/{len(STAGES)}] Running {name}...', flush=True)
            result = execute_stage(name, commands[name], output, timeout=args.timeout_seconds, env=env)
            report['stages'][index] = result
            write_report(output, report)
            print(f"  {result['status']} ({result['elapsed_seconds']}s)", flush=True)
        report['source_unchanged_during_run'] = source_snapshot() == snapshot
        statuses = {row['status'] for row in report['stages']}
        report['status'] = ('FAIL' if 'FAIL' in statuses or not report['source_unchanged_during_run'] else
                            'PARTIAL' if 'NOT_RUN' in statuses else
                            'PASS_WITH_WARNINGS' if 'WARN' in statuses else 'PASS')
    except KeyboardInterrupt:
        report['status'] = 'INTERRUPTED'
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        write_report(output, report)
    print(f"{report['status']}: {output / 'report.md'}", flush=True)
    return 1 if report['status'] in {'FAIL', 'INTERRUPTED'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
