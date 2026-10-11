"""Exercise real Global/JP switching, Japanese search, persistence and header layout."""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.environ.get('CHIBI_STUDIO_URL', 'http://127.0.0.1:8084').rstrip('/')
OUTPUT = Path(__file__).resolve().parents[1] / '.local/chibi-region-check'
OUTPUT.mkdir(parents=True, exist_ok=True)


def ready(page, model=None):
    page.wait_for_function("id => document.querySelector('#status').dataset.state === 'ready' && (!id || document.querySelector('#viewport').dataset.model === id)", arg=model, timeout=60000)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 900}, reduced_motion='reduce')
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    catalog = context.request.get(URL + '/api/chibi-models').json()['models']
    jp = next(entry for entry in catalog if entry['id'] == 'jp-1120')
    rice = next(entry for entry in catalog if entry['id'] == 'jp-1030')
    assert len(catalog) == 270
    global_models = [entry for entry in catalog if 'global' in entry['available_in']]
    assert len(global_models) == 109
    assert len({(entry['character_id'], entry['costume']) for entry in catalog}) == 270
    assert all(len(entry['animation_labels']) > 100 and len(entry['faces']['presets']) == 24 for entry in catalog)
    # Existing visitors keep their outfit when the old Global GLB is replaced.
    page.add_init_script("if (!localStorage.getItem('chibi-studio-model')) localStorage.setItem('chibi-studio-model', '1030');")
    page.goto(URL + '/chibi')
    ready(page, 'jp-1030')
    assert page.locator('html').get_attribute('data-library-region') == 'global'
    assert page.locator('#animation option').count() > 100
    assert page.locator('[data-expression]').count() == 24
    assert page.locator('#character option').count() == 69
    # A Global character's JP-only alternate outfits must also stay hidden.
    global_rice = {entry['id'] for entry in global_models if entry['character_id'] == 1030}
    assert set(page.locator('#outfit option').evaluate_all('items => items.map(item => item.value)')) == global_rice
    assert page.locator('#github-link').get_attribute('href') == 'https://github.com/daftuyda/chibi-studio'
    assert page.locator('#github-link').get_attribute('target') == '_blank'
    page.locator('#character').select_option('1030')
    ready(page, 'jp-1030')
    page.locator('#library-toggle').click()
    ready(page, 'jp-1030')
    assert page.locator('#library-region-label').inner_text() == 'JP'
    assert page.locator('#character option').count() == 135
    assert page.locator('#outfit option').count() > len(global_rice)
    assert page.locator('#animation option').count() > 100
    page.locator('#character-search').fill(rice['name_jp'])
    assert page.locator('#character option').count() == 1
    assert page.locator('#character option').get_attribute('value') == '1030'
    page.locator('#character-search').fill(jp['outfit_jp'])
    assert page.locator('#character option[value="1120"]').count() == 1
    page.locator('#character-search').fill('Calstone')
    page.locator('#character').select_option('1120')
    ready(page, 'jp-1120')
    assert page.locator('#stage-name').inner_text() == jp['display_name']
    page.locator('#library-toggle').click()
    ready(page, 'jp-1030')
    assert not page.locator('#character-search').input_value()
    assert page.locator('#character option[value="1120"]').count() == 0
    page.locator('#library-toggle').click()
    ready(page, 'jp-1120')
    page.reload()
    ready(page, 'jp-1120')
    assert page.locator('#library-region-label').inner_text() == 'JP'
    # A superseded region request must not put the wrong model back on the stage.
    page.evaluate("() => { const b = document.querySelector('#library-toggle'); b.click(); b.click(); b.click(); }")
    ready(page, 'jp-1030')
    assert page.locator('html').get_attribute('data-library-region') == 'global'
    page.locator('#library-toggle').click()
    ready(page, 'jp-1120')
    if page.locator('html').get_attribute('data-ui-theme') != 'dark':
        page.locator('#ui-theme-toggle').click()
    page.screenshot(path=OUTPUT / 'desktop-dark.png')
    for width in (320, 390):
        page.set_viewport_size({'width': width, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow at {width}px'
        for selector in ('#library-toggle', '#github-link', '#ui-theme-toggle'):
            bounds = page.locator(selector).bounding_box()
            assert bounds and bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
            assert bounds['height'] >= 36
        page.locator('#library-toggle').click()
        ready(page, 'jp-1030')
        page.locator('#library-toggle').click()
        ready(page, 'jp-1120')
        page.screenshot(path=OUTPUT / f'mobile-{width}-dark.png')
        page.locator('#ui-theme-toggle').click()
        page.screenshot(path=OUTPUT / f'mobile-{width}-light.png')
        page.locator('#ui-theme-toggle').click()
    assert not errors, errors
    assert page.locator('#message').is_hidden()
    print('Global/JP switching, Japanese/English search, restored selections, rapid switching and 320/390px headers passed.')
    browser.close()
