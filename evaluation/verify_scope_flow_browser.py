"""Offline browser acceptance on a disposable database and fresh browser profile.

Requires Playwright and a local Chromium executable; no provider requests occur.
"""
import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.database import Database
from app.server import make_server


def verify(executable, output):
    from playwright.sync_api import sync_playwright, expect

    output.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    with tempfile.TemporaryDirectory(prefix='sweaterco-browser-') as temporary:
        path = Path(temporary) / 'browser.sqlite3'
        with Database(path):
            pass
        server = make_server(0, path, as_of=date(2026, 4, 1), require_auth=False)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=executable, headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})

                def page():
                    tab = context.new_page()
                    tab.on('pageerror', lambda error: errors.append(str(error)))
                    tab.goto(base + '/chat?new=1')
                    expect(tab.locator('#chat-input')).to_be_enabled()
                    expect(tab.locator('#chat-mode')).to_have_value('offline')
                    return tab

                def post(tab, click):
                    with tab.expect_response(lambda response: response.request.method == 'POST'
                                             and '/api/chat/sessions/' in response.url
                                             and response.url.endswith('/turns')) as received:
                        click()
                    result = received.value.json()
                    expect(tab.locator('#chat-input')).to_be_enabled()
                    return result

                def send(tab, message):
                    tab.locator('#chat-input').fill(message)
                    return post(tab, lambda: tab.locator('#chat-send').click())

                def confirm(tab):
                    return post(tab, lambda: tab.get_by_role('button', name='Confirm allocation', exact=True).click())

                refused = page()
                result = send(refused, 'Allocate ORD-045 to OldMill; exclude W3.')
                assert not result['committed'] and result['validation_report']['alternatives']
                expect(refused.get_by_text('Options requiring your authorization', exact=True)).to_be_visible()
                assert refused.get_by_role('button', name='Confirm allocation', exact=True).count() == 0
                checks.append('Blocked request displays conditional alternatives without approval buttons or production writes.')
                refused.screenshot(path=str(output / 'alternatives-desktop.png'))
                refused.set_viewport_size({'width': 390, 'height': 844})
                assert refused.evaluate('document.documentElement.scrollWidth <= innerWidth')
                refused.get_by_text('Options requiring your authorization', exact=True).scroll_into_view_if_needed()
                refused.screenshot(path=str(output / 'alternatives-mobile.png'))
                checks.append('390px mobile alternatives view has no horizontal page overflow.')

                first = page()
                original = send(first, 'Allocate ORD-045 fastest.')
                assert original['session']['recommendation']['result']['allocation'][0]['workshop_id'] == 'W6'
                other = page()
                send(other, 'Allocate ORD-096 fastest.')
                assert confirm(other)['committed']
                changed = confirm(first)
                assert not changed['committed'] and changed['reason_code'] == 'REVIEW_CHANGED'
                assert changed['session']['recommendation']['result']['allocation'][0]['workshop_id'] == 'W8'
                first.reload()
                summary = first.get_by_text('What changed since your review?', exact=True)
                expect(summary).to_be_visible()
                summary.click()
                expect(first.get_by_text('No allocation was committed by this attempt. Review the new plan before confirming.', exact=True)).to_be_visible()
                first.screenshot(path=str(output / 'review-changed-desktop.png'))
                approved = confirm(first)
                assert approved['committed']
                first.reload()
                expect(first.get_by_role('button', name='Committed', exact=True)).to_be_disabled()
                with Database(path) as db:
                    assert db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0] == 2
                checks.append('Concurrent-order change returns W6 to W8 for re-review, survives reload, then commits once after renewed confirmation.')

                split = page()
                result = send(split, 'Allocate ORD-055 fastest using at most two workshops.')
                plans = result['session']['recommendation']['result']['candidate_plans']
                assert any(len(candidate['allocation']) == 2 for candidate in plans)
                split.get_by_text('Compare complete candidate plans', exact=True).click()
                expect(split.get_by_text('Recommended plan', exact=True)).to_be_visible()
                split.get_by_text('Compare complete candidate plans', exact=True).scroll_into_view_if_needed()
                split.screenshot(path=str(output / 'split-candidates-desktop.png'))
                checks.append('Complete split candidates render quantities, delivery dates, cost and quality.')
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=20)
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'mode': 'offline',
              'browser': 'headless local Chromium, fresh profile', 'checks': checks,
              'page_errors': errors, 'production_database_touched': False,
              'live_model_calls': 0, 'status': 'PASS'}
    (output / 'browser.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.executable, args.output_dir), indent=2))
