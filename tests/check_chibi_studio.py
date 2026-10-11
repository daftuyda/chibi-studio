"""Verify stage changes and decode real browser-generated GIFs (local assets only)."""
import io
import os
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageChops, ImageSequence
from playwright.sync_api import sync_playwright

URL = os.environ.get('CHIBI_STUDIO_URL', 'http://127.0.0.1:8084').rstrip('/')
REGION = os.environ.get('CHIBI_STUDIO_REGION', 'global')
assert REGION in ('global', 'jp'), 'CHIBI_STUDIO_REGION must be global or jp.'
OUTPUT = Path(__file__).resolve().parents[1] / '.local' / ('chibi-studio-check-jp' if REGION == 'jp' else 'chibi-studio-check')
OUTPUT.mkdir(parents=True, exist_ok=True)


def input_value(page, selector, value):
    page.locator(selector).evaluate('(el, value) => { el.value = value; el.dispatchEvent(new Event("input", {bubbles: true})); }', value)


def gif_file(page, filename, shape='square', fps='10', duration='2', orbit=False):
    page.locator('#save-gif').click()
    page.locator('#gif-size').select_option('256')
    page.locator('#gif-shape').select_option(shape)
    page.locator('#gif-fps').select_option(fps)
    page.locator('#gif-duration').select_option(duration)
    page.locator('#gif-orbit').set_checked(orbit)
    page.locator('#gif-start').click()
    page.wait_for_function("['ready', 'error'].includes(document.querySelector('#gif-dialog').dataset.state)", timeout=120000)
    assert page.locator('#gif-dialog').get_attribute('data-state') == 'ready', page.locator('#gif-status').inner_text()
    with page.expect_download() as download:
        page.locator('#gif-download').click()
    download.value.save_as(OUTPUT / filename)
    assert 'vampire-makeover' in download.value.suggested_filename
    page.locator('#gif-close').click()
    return Image.open(OUTPUT / filename)


def check_gif(image, size, frames, milliseconds=2000, transparent=False):
    assert image.format == 'GIF' and image.size == size
    assert image.n_frames == frames and image.info['loop'] == 0
    decoded, duration = [], 0
    for frame in ImageSequence.Iterator(image):
        duration += frame.info['duration']
        rgba = frame.convert('RGBA')
        assert rgba.getpixel((0, 0))[3] == (0 if transparent else 255)
        if transparent:
            assert frame.disposal_method == 2
            assert rgba.getchannel('A').getextrema() == (0, 255)
        decoded.append(rgba.copy())
    assert abs(duration - milliseconds) <= 10, duration
    assert ImageChops.difference(decoded[0], decoded[frames // 2]).convert('RGB').getbbox(), 'Export must visibly animate.'


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 1100}, reduced_motion='reduce')
    errors, remote = [], []
    context.on('request', lambda request: remote.append(request.url)
               if urlsplit(request.url).scheme in ('http', 'https') and urlsplit(request.url).netloc != urlsplit(URL).netloc else None)
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
    page.goto(URL + '/chibi')
    page.wait_for_function("document.querySelector('#status').dataset.state === 'ready'")
    if REGION == 'jp':
        page.locator('#library-toggle').click()
        page.wait_for_function("document.documentElement.dataset.libraryRegion === 'jp' && document.querySelector('#status').dataset.state === 'ready'")
    prefix = 'jp-'
    page.locator('#character').select_option('1030')
    page.wait_for_function("id => document.querySelector('#viewport').dataset.model === id", arg=prefix + '1030')
    page.locator('#outfit').select_option(prefix + '1030-40')
    page.wait_for_function("id => document.querySelector('#viewport').dataset.model === id", arg=prefix + '1030-40')
    page.locator('#animation').select_option(label='Run')
    page.locator('[data-expression=happy]').click()
    input_value(page, '#timeline', '.28')
    canvas = page.locator('#viewport canvas')
    baseline = canvas.screenshot()
    page.locator('#show-platform').uncheck()
    assert canvas.screenshot() != baseline
    page.locator('#show-platform').check()
    page.locator('#studio-lighting').check()
    assert canvas.screenshot() != baseline, 'Lighting must affect the character.'
    input_value(page, '#ambient-light', '0.4')
    input_value(page, '#key-light', '3.5')
    input_value(page, '#light-direction', '-80')
    left = canvas.screenshot()
    input_value(page, '#light-direction', '80')
    assert canvas.screenshot() != left, 'Moving the light must change shading.'
    input_value(page, '#light-color', '#ffb8da')
    page.locator('#show-shadows').uncheck()
    assert canvas.screenshot() != baseline
    page.locator('#show-shadows').check()
    page.locator('#background-mode').select_option('gradient')
    input_value(page, '#background-color', '#112244')
    input_value(page, '#background-color-2', '#a177b7')
    snapshot = Image.open(io.BytesIO(canvas.screenshot())).convert('RGB')
    assert snapshot.getpixel((3, 3)) != snapshot.getpixel((3, snapshot.height - 4))
    page.locator('.stage-card').screenshot(path=OUTPUT / 'custom-stage.png')
    before_export = canvas.screenshot()
    check_gif(gif_file(page, 'rice-studio.gif'), (256, 256), 20)
    assert canvas.screenshot() == before_export, 'Export must restore the paused pose, camera and viewport size.'
    assert page.locator('#play-pause').get_attribute('aria-label') == 'Play animation'

    page.locator('#background-mode').select_option('transparent')
    page.locator('#show-platform').uncheck()
    check_gif(gif_file(page, 'rice-transparent.gif', shape='portrait', fps='25', orbit=True), (192, 256), 50, transparent=True)
    with page.expect_download() as download:
        page.locator('#save-image').click()
    download.value.save_as(OUTPUT / 'transparent.png')
    assert Image.open(OUTPUT / 'transparent.png').convert('RGBA').getpixel((0, 0))[3] == 0

    # A local background is included in the actual GIF, with no network upload.
    background = io.BytesIO(); Image.new('RGB', (80, 40), '#22cc77').save(background, format='PNG')
    page.locator('#background-mode').select_option('image')
    page.locator('#background-image').set_input_files({'name': 'background.png', 'mimeType': 'image/png', 'buffer': background.getvalue()})
    page.wait_for_function("document.querySelector('#background-image-note').textContent.includes('session')")
    uploaded = gif_file(page, 'rice-background.gif', shape='wide')
    check_gif(uploaded, (256, 192), 20)
    uploaded.seek(0)
    color = uploaded.convert('RGB').getpixel((0, 0))
    assert max(abs(a - b) for a, b in zip(color, (34, 204, 119))) < 12, color

    # Cancel a large job, then immediately create another one with the same renderer.
    page.locator('#save-gif').click()
    page.locator('#gif-size').select_option('768'); page.locator('#gif-fps').select_option('25'); page.locator('#gif-duration').select_option('10')
    page.locator('#gif-start').click()
    page.wait_for_function("document.querySelector('#gif-progress').value > 0")
    page.locator('#gif-cancel').click()
    page.wait_for_function("document.querySelector('#gif-dialog').dataset.state === 'cancelled'")
    assert not page.locator('#gif-start').is_disabled()
    page.locator('#gif-close').click()
    check_gif(gif_file(page, 'after-cancel.gif'), (256, 256), 20)

    # Saved colours survive reload, while the uploaded image stays session-only.
    page.reload()
    page.wait_for_function("document.querySelector('#status').dataset.state === 'ready'")
    assert page.locator('#background-mode').input_value() == 'solid'
    assert page.locator('#background-color').input_value() == '#112244'
    assert not page.locator('#show-platform').is_checked()
    page.locator('#reset-stage').click()
    assert page.locator('#show-platform').is_checked()
    assert not page.locator('#studio-lighting').is_checked()
    assert page.locator('#background-color').input_value() == '#eeebf7'

    # An unavailable encoder must recover without breaking the stage.
    page.evaluate("() => { window.Worker = class { constructor() { throw new Error('Encoder unavailable for this test'); } }; }")
    page.locator('#save-gif').click(); page.locator('#gif-start').click()
    page.wait_for_function("document.querySelector('#gif-dialog').dataset.state === 'error'")
    assert not page.locator('#gif-start').is_disabled()
    page.locator('#gif-close').click()
    page.locator('[data-expression=excited]').click()
    assert canvas.screenshot()

    page.set_viewport_size({'width': 390, 'height': 844})
    page.locator('#save-gif').click()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('#gif-dialog').evaluate('el => el.scrollWidth <= el.clientWidth')
    page.screenshot(path=OUTPUT / 'mobile-export.png')
    assert not errors, errors
    assert not remote, remote
    print('Studio checks passed: real GIF frames/timing/transparency, backgrounds, platform, cancellation, recovery, restored preview, saved stage and mobile. No external requests.')
    browser.close()
