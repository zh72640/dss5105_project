"""Exercise dashboard charts and order tracing using isolated, deterministic data."""
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
from app.services.allocation.dispatch import seed_allocation
from app.services.production.lifecycle import inspect_order, process_event


def verify(executable, output):
    from playwright.sync_api import sync_playwright, expect

    output.mkdir(parents=True, exist_ok=False)
    checks, errors = [], []
    with tempfile.TemporaryDirectory(prefix='sweaterco-operations-') as directory:
        db = str(Path(directory) / 'operations.sqlite3')
        with Database(db) as database:
            imported = database.connection.execute("SELECT order_id FROM orders WHERE state='COMPLETED' LIMIT 1").fetchone()[0]
        seed_allocation('Allocate ORD-045 to Nimble Needle.', db_path=db, request_id='first', actor='dispatcher')

        def event(action, event_id, **kwargs):
            result = process_event(action, 'ORD-045', db_path=db, event_id=event_id,
                expected_version=inspect_order('ORD-045', db_path=db)['version'],
                actor='production-operator', reason='Browser acceptance fixture', **kwargs)
            assert result['result']['success'], result

        event('complete', 'partial', workshop_id='W6', pieces=30)
        event('cancel', 'cancel')
        seed_allocation('Allocate ORD-045 to Nimble Needle.', db_path=db, request_id='second', actor='dispatcher')
        event('reassign', 'reassign', preferred_workshop='W8')
        server = make_server(0, db, as_of=date(2026, 4, 1), require_auth=False)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=executable, headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1100})
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))

                def screenshot(name):
                    page.mouse.move(0, 0)
                    page.evaluate('document.activeElement?.blur(); window.scrollTo(0, 0)')
                    page.evaluate('new Promise(requestAnimationFrame)')
                    page.screenshot(path=str(output / name), full_page=True)

                page.goto(base)
                expect(page.locator('.ops-chart')).to_have_count(4)
                expect(page.locator('.ops-bar-row')).to_have_count(24)
                expect(page.locator('.ops-order-row').first).to_have_attribute('data-order-id', 'ORD-045')
                quality = page.locator('.ops-chart').filter(has=page.get_by_role('heading', name='Production quality'))
                quality.locator('[data-workshop="W6"]').hover()
                expect(page.get_by_role('tooltip')).to_contain_text('Planning estimate')
                expect(page.get_by_role('tooltip')).to_contain_text('5 %')
                page.keyboard.press('Escape')
                expect(page.get_by_role('tooltip')).to_be_hidden()
                cost = page.locator('.ops-chart').filter(has=page.get_by_role('heading', name='Cost comparison'))
                cost.locator('[data-workshop="W6"]').focus()
                expect(page.get_by_role('tooltip')).to_contain_text('Quoted rate')
                page.keyboard.press('Escape')
                availability = page.locator('.ops-chart').filter(has=page.get_by_role('heading', name='Workshop availability'))
                availability.locator('.ops-legend-item').first.hover()
                expect(page.get_by_role('tooltip')).to_contain_text('Active')
                page.keyboard.press('Escape')
                checks.append('Four charts render with real data; mouse and keyboard tooltips expose quality, unit cost and availability.')
                screenshot('dashboard-desktop.png')

                page.locator('#tracking-search').fill('ORD-045')
                expect(page.locator('.ops-order-row')).to_have_count(1)
                page.locator('.ops-order-row').click()
                expect(page.locator('#order-tracking')).to_be_visible()
                expect(page.locator('.ops-journey [aria-current="step"]')).to_contain_text('Production')
                expect(page.locator('.ops-timeline')).to_contain_text('Allocation cancelled')
                expect(page.locator('.ops-timeline')).to_contain_text('Remaining pieces reassigned')
                expect(page.locator('.ops-completion')).to_contain_text('20% complete')
                screenshot('order-tracking-desktop.png')
                checks.append('Dashboard search opens the order journey with partial progress, approval actors, cancellation and reassignment.')

                page.locator('#event-action').select_option('complete')
                page.locator('#event-reason').fill('Acceptance completion')
                page.locator('#complete-workshop').select_option('W8')
                page.locator('#complete-pieces').fill('120')
                page.get_by_role('button', name='Review production change').click()
                page.locator('#event-confirm').click()
                expect(page.locator('.ops-completion')).to_contain_text('100% complete')
                expect(page.locator('.ops-journey [aria-current="step"]')).to_contain_text('Completed')
                expect(page.locator('#production-form')).to_be_hidden()
                page.reload()
                expect(page.locator('#order-tracking')).to_be_visible()
                expect(page.locator('#production-order')).to_have_value('ORD-045')
                expect(page.locator('.ops-completion')).to_contain_text('100% complete')
                checks.append('Explicit production confirmation updates the journey and dashboard; completion persists after reload.')

                page.locator('#production-order').fill(imported)
                page.get_by_role('button', name='Load current order').click()
                expect(page.locator('.ops-stage.unknown')).to_have_count(2)
                expect(page.locator('.ops-timeline')).to_contain_text('Imported completion record')
                checks.append('Imported completed orders retain unknown intermediate milestones instead of fabricated progress.')

                page.set_viewport_size({'width': 390, 'height': 844})
                screenshot('order-tracking-mobile.png')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.goto(base)
                expect(page.locator('.ops-chart')).to_have_count(4)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.locator('#tracking-search').fill('no-such-order')
                expect(page.get_by_text('No orders match these filters.', exact=True)).to_be_visible()
                page.locator('#tracking-search').fill('')
                page.locator('#tracking-filter').select_option('COMPLETED')
                expect(page.locator('.ops-order-row').first).to_contain_text('Completed')
                screenshot('dashboard-mobile.png')
                checks.append('390px mobile dashboard and tracking have no horizontal overflow; search and status filters work.')
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=20)
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'status': 'PASS',
              'checks': checks, 'page_errors': errors, 'live_model_calls': 0,
              'production_database_touched': False, 'mode': 'offline'}
    (output / 'operations-browser.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.executable, args.output_dir), indent=2))
