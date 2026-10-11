"""Exercise the included chibi library in Chrome, including visible animated frames.

Start viewer.py with the included models, then run this script.
CHIBI_STUDIO_URL can select a different address.
"""
import json
import os
import struct
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

URL = os.environ.get('CHIBI_STUDIO_URL', 'http://127.0.0.1:8084').rstrip('/')
OUTPUT = Path(__file__).resolve().parents[1] / '.local' / 'chibi-browser'
OUTPUT.mkdir(parents=True, exist_ok=True)


def glb(metadata):
    content = json.dumps(metadata).encode()
    content += b' ' * (-len(content) % 4)
    return struct.pack('<IIIII', 0x46546C67, 2, 20 + len(content), len(content), 0x4E4F534A) + content


def ready(page):
    page.wait_for_function("document.querySelector('#status').dataset.state === 'ready'")
    assert page.locator('#viewport').get_attribute('data-loaded') == 'true'


def pause(page):
    if page.locator('#play-pause').get_attribute('aria-label') == 'Pause animation':
        page.locator('#play-pause').click()
    page.locator('#blink').uncheck()


def outfit(page, entry):
    key = str(entry.get('character_id') or entry['id'])
    page.locator('#character').select_option(key)
    ready(page)
    if page.locator('#outfit').input_value() != entry['id']:
        page.locator('#outfit').select_option(entry['id'])
    page.wait_for_function("id => document.querySelector('#status').dataset.state === 'ready' && document.querySelector('#viewport').dataset.model === id", arg=entry['id'])


def seek(page, fraction):
    page.locator('#timeline').evaluate('(el, value) => { el.value = value; el.dispatchEvent(new Event("input")); }', fraction)
    page.wait_for_timeout(80)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 1100})
    errors, remote_requests = [], []
    context.on('page', lambda page: page.on('pageerror', lambda err: errors.append(str(err))))
    context.on('request', lambda request: remote_requests.append(request.url)
               if urlsplit(request.url).scheme in ('http', 'https') and urlsplit(request.url).netloc != urlsplit(URL).netloc else None)
    catalog = context.request.get(URL + '/api/chibi-models').json()['models']
    assert catalog, 'Restore the included model library before running this browser check.'
    model_bytes = context.request.get(URL + catalog[0]['model_url']).body()
    page = context.new_page()
    page.goto(URL + '/chibi')
    ready(page)
    outfit(page, catalog[0])
    assert page.locator('#stage-name').inner_text() == catalog[0]['display_name']
    assert catalog[0]['outfit'] in page.locator('#outfit option:checked').inner_text()
    assert page.locator('#viewport canvas').count() == 1
    assert int(page.locator('#viewport').get_attribute('data-animations')) >= 2
    assert not page.locator('[data-expression=happy]').is_disabled()
    pause(page)
    seek(page, 0)
    canvas = page.locator('#viewport canvas')
    neutral = canvas.screenshot()
    page.wait_for_timeout(180)
    assert canvas.screenshot() == neutral, 'Paused animation with blinking off should remain still.'
    expressions = page.locator('[data-expression]').evaluate_all('buttons => buttons.map(button => button.dataset.expression)')
    for expression in expressions:
        if expression == 'neutral':
            continue
        page.locator(f'[data-expression={expression}]').click()
        page.wait_for_timeout(60)
        assert canvas.screenshot() != neutral, f'{expression} must change the visible face.'
    page.locator('[data-expression=neutral]').click()

    if not page.locator('#motion-category').is_disabled():
        page.locator('#match-expression').check()
        page.locator('#motion-category').select_option('Dance')
        assert page.locator('[data-expression=happy]').get_attribute('aria-pressed') == 'true'
        page.locator('[data-expression=shy]').click()
        assert not page.locator('#match-expression').is_checked(), 'A manually chosen face should persist.'
        page.locator('#motion-category').select_option('Movement')
        assert page.locator('[data-expression=shy]').get_attribute('aria-pressed') == 'true'
        page.locator('#motion-category').select_option('')
        page.locator('[data-expression=neutral]').click()

    # Each original clip must actually move the mesh, including after a clip change.
    clip_count = page.locator('#animation option').count()
    for index in range(clip_count):
        page.locator('#animation').select_option(str(index))
        seek(page, 0)
        first = canvas.screenshot()
        seek(page, 0.37)
        assert canvas.screenshot() != first, f'Animation {index} has no visible motion.'
    page.locator('#animation').select_option('0')
    seek(page, 0)
    page.locator('#speed').select_option('2')
    page.locator('#play-pause').click()
    page.wait_for_timeout(220)
    page.locator('#play-pause').click()
    assert float(page.locator('#timeline').input_value()) > 0
    page.locator('#speed').select_option('1')
    seek(page, 0)

    # Pointer controls orbit the real model and reset returns to the original framing.
    before = canvas.screenshot()
    box = canvas.bounding_box()
    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    page.mouse.down()
    page.mouse.move(box['x'] + box['width'] / 2 + 130, box['y'] + box['height'] / 2, steps=12)
    page.mouse.up()
    page.wait_for_timeout(400)
    assert canvas.screenshot() != before
    page.locator('#reset-camera').click()
    page.wait_for_timeout(500)

    for theme in ('peach', 'mint', 'night', 'lilac'):
        page.locator(f'button[data-theme={theme}]').click()
        assert page.locator(f'button[data-theme={theme}]').get_attribute('aria-pressed') == 'true'
    page.locator('#show-grid').check()
    page.locator('#show-grid').uncheck()
    with page.expect_download() as saved:
        page.locator('#save-image').click()
    saved.value.save_as(OUTPUT / 'saved-character.png')
    assert (OUTPUT / 'saved-character.png').read_bytes().startswith(b'\x89PNG')
    page.evaluate('window.scrollTo(0, 0)')
    page.screenshot(path=OUTPUT / 'desktop.png', full_page=True)

    # Failed imports preserve the character, and an imported file cannot load external resources.
    for filename, content, message in [
        ('broken.glb', b'not a glb', 'complete GLB'),
        ('external.glb', glb({'asset': {'version': '2.0'}, 'buffers': [{'uri': 'https://invalid.example/model.bin', 'byteLength': 4}]}), 'self-contained'),
        ('empty.glb', glb({'asset': {'version': '2.0'}, 'scenes': [{'nodes': []}], 'scene': 0}), 'no visible'),
    ]:
        page.locator('#model-file').set_input_files({'name': filename, 'mimeType': 'model/gltf-binary', 'buffer': content})
        page.wait_for_function("document.querySelector('#status').dataset.state === 'error'")
        assert message in page.locator('#message').inner_text()
        assert page.locator('#status').inner_text() == 'Previous character kept'
        assert not page.locator('#animation').is_disabled()
    seek(page, 0.25)
    page.locator('#model-file').set_input_files({'name': 'local-character.glb', 'mimeType': 'model/gltf-binary', 'buffer': model_bytes})
    ready(page)
    assert page.locator('#stage-name').inner_text() == catalog[0]['display_name']
    assert 'no file uploaded' in page.locator('#model-details').text_content()
    assert not page.locator('[data-expression=happy]').is_disabled(), 'GLB extras must retain face controls when opened directly.'
    for entry in catalog[:3]:
        outfit(page, entry)
        assert page.locator('#stage-name').inner_text() == entry['display_name']
    assert page.locator('#viewport canvas').count() == 1

    mobile = context.new_page()
    mobile.set_viewport_size({'width': 390, 'height': 844})
    mobile.emulate_media(reduced_motion='reduce')
    mobile.goto(URL + '/chibi')
    ready(mobile)
    assert mobile.locator('#play-pause').get_attribute('aria-label') == 'Play animation'
    assert not mobile.locator('#blink').is_checked()
    assert mobile.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile page should not scroll sideways.'
    mobile.screenshot(path=OUTPUT / 'mobile.png', full_page=True)

    # No exports is a usable state, and the local file picker still works.
    empty = context.new_page()
    empty.route('**/api/chibi-models', lambda route: route.fulfill(json={'models': []}))
    empty.goto(URL + '/chibi')
    empty.wait_for_function("document.querySelector('#status').textContent === 'Waiting for a character'")
    assert empty.locator('#empty-state').is_visible()
    empty.locator('#model-file').set_input_files({'name': 'rice.glb', 'mimeType': 'model/gltf-binary', 'buffer': model_bytes})
    ready(empty)
    assert not empty.locator('#empty-state').is_visible()
    assert not errors, errors
    assert not remote_requests, remote_requests
    print(f'Chibi browser checks passed: {clip_count} original clips, {len(expressions)} expressions, outfit titles, camera, file import, screenshot, mobile and empty state. No external requests.')
    browser.close()
