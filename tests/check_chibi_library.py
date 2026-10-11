"""Load every cached outfit in Chrome and exercise its rig, title and expressions."""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.environ.get('CHIBI_STUDIO_URL', 'http://127.0.0.1:8084').rstrip('/')
OUTPUT = Path(__file__).resolve().parents[1] / '.local/chibi-library-check'
OUTPUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 1100}, reduced_motion='reduce')
    catalog = context.request.get(URL + '/api/chibi-models').json()['models']
    assert catalog, 'Import a character library first.'
    if selected := os.environ.get('CHIBI_STUDIO_MODEL_IDS'):
        requested = set(selected.split(','))
        catalog = [entry for entry in catalog if entry['id'] in requested]
        assert {entry['id'] for entry in catalog} == requested, 'A requested outfit is unavailable.'
    page = context.new_page()
    errors, results = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
    page.goto(URL + '/chibi')
    page.wait_for_function("document.querySelector('#status').dataset.state === 'ready'")
    for index, entry in enumerate(catalog):
        region = entry.get('region', 'global')
        if page.locator('html').get_attribute('data-library-region') != region:
            page.locator('#library-toggle').click()
            page.wait_for_function("region => document.documentElement.dataset.libraryRegion === region && document.querySelector('#status').dataset.state === 'ready'", arg=region)
        key = str(entry.get('character_id') or entry['id'])
        if page.locator('#character').input_value() != key:
            page.locator('#character').select_option(key)
            page.wait_for_function("document.querySelector('#status').dataset.state === 'ready'")
        if page.locator('#outfit').input_value() != entry['id']:
            page.locator('#outfit').select_option(entry['id'])
        page.wait_for_function("id => document.querySelector('#status').dataset.state === 'ready' && document.querySelector('#viewport').dataset.model === id", arg=entry['id'])
        assert page.locator('#stage-name').inner_text() == entry['display_name']
        assert entry['outfit'] in page.locator('#outfit option:checked').inner_text()
        count = page.locator('#animation option').count()
        assert count >= 2
        assert page.locator('[data-expression]').count() >= 4
        assert not page.locator('#cloth-physics').is_disabled(), entry['id']
        page.locator('#animation').select_option(label='Run')
        page.locator('#timeline').evaluate('el => { el.value = .35; el.dispatchEvent(new Event("input")); }')
        page.locator('[data-expression=happy]').click()
        assert not errors, {'outfit': entry['id'], 'errors': errors}
        assert page.locator('#viewport canvas').count() == 1
        results.append({'id': entry['id'], 'name': entry['display_name'], 'animations': count,
                        'expressions': page.locator('[data-expression]').count(), 'physics': True, 'status': 'rendered'})
        if index % 20 == 0 or entry['id'] in ('1030-40', '1003-02', '1007-30', '1056-10'):
            page.locator('.stage-card').screenshot(path=OUTPUT / f"{entry['id']}.png")
        if (index + 1) % 20 == 0:
            print(f'Rendered {index + 1}/{len(catalog)} outfits', flush=True)
    (OUTPUT / 'report.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'All {len(results)} outfits rendered with their full titles, animations and face controls. No browser errors.')
    browser.close()
