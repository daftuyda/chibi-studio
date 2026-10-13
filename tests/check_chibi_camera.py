"""Check camera movement, input focus, mobile gestures and export restoration."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = os.environ.get('CHIBI_STUDIO_URL', 'http://127.0.0.1:8084').rstrip('/')
OUTPUT = Path(__file__).resolve().parents[1] / '.local/camera-checks'
OUTPUT.mkdir(parents=True, exist_ok=True)


def expose_scene(route):
    response = route.fetch()
    route.fulfill(response=response, body=response.text() + '\nwindow.cameraTestScene = scene;\n')


def state(page):
    return page.evaluate('''() => {
      const s=window.cameraTestScene;
      return {position:s.camera.position.toArray(), target:s.controls.target.toArray(),
        offset:s.camera.position.clone().sub(s.controls.target).toArray()};
    }''')


def close(a, b):
    return max(abs(x-y) for x, y in zip(a, b)) < 1e-6


def ready(page):
    page.wait_for_function('window.cameraTestScene?.model && document.querySelector("#status").dataset.state === "ready"')
    if page.locator('#play-pause').get_attribute('aria-label') == 'Pause animation':
        page.locator('#play-pause').click()
    page.locator('#blink').uncheck()


with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome')
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    context.route('**/chibi-viewer.js', expose_scene)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(URL + '/chibi')
    ready(page)
    initial = state(page)
    for direction, axis, sign in [('left', 0, -1), ('right', 0, 1), ('up', 1, 1), ('down', 1, -1)]:
        page.locator('#reset-camera').click()
        page.locator(f'[data-pan={direction}]').click()
        moved = state(page)
        assert sign * (moved['target'][axis] - initial['target'][axis]) > .01
        assert close(initial['offset'], moved['offset']), 'Movement must translate the camera and target together.'
    page.locator('#reset-camera').click()
    assert close(initial['position'], state(page)['position'])
    page.locator('#viewport').focus()
    page.keyboard.press('ArrowRight')
    moved = state(page)
    assert moved['target'][0] > initial['target'][0]
    page.locator('#character-search').focus()
    page.keyboard.press('ArrowLeft')
    assert close(moved['position'], state(page)['position']), 'Typing in a field must not move the camera.'

    for mode in ['right-drag', 'move-drag']:
        page.locator('#reset-camera').click()
        if mode == 'move-drag':
            page.locator('#camera-pan-mode').click()
        box = page.locator('#viewport canvas').bounding_box()
        x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
        page.mouse.move(x, y)
        page.mouse.down(button='right' if mode == 'right-drag' else 'left')
        page.mouse.move(x + 60, y - 35, steps=10)
        page.mouse.up(button='right' if mode == 'right-drag' else 'left')
        page.wait_for_timeout(400)
        moved = state(page)
        assert not close(initial['target'], moved['target'])
        assert close(initial['offset'], moved['offset'])
    page.locator('#camera-pan-mode').click()
    page.locator('#reset-camera').click()
    assert close(initial['target'], state(page)['target'])
    page.locator('[data-pan=left]').click()
    page.locator('[data-pan=up]').click()
    before = state(page)
    page.evaluate('''() => {
      const s=window.cameraTestScene, capture=s.beginCapture(128,128,true);
      s.panCamera(1,1); s.resetCamera();
      capture.render(.2,.4); capture.restore();
    }''')
    after = state(page)
    assert close(before['target'], after['target']) and close(before['position'], after['position'])
    page.screenshot(path=str(OUTPUT / 'desktop.png'))
    assert not errors, errors
    context.close()

    mobile = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
    mobile.route('**/chibi-viewer.js', expose_scene)
    page = mobile.new_page()
    page.goto(URL + '/chibi')
    ready(page)
    page.locator('[data-pan=up]').tap()
    page.locator('#reset-camera').tap()
    initial = state(page)
    box = page.locator('#viewport canvas').bounding_box()
    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    cdp = mobile.new_cdp_session(page)
    points = lambda dx, dy: [{'x': x - 30 + dx, 'y': y + dy, 'id': 1}, {'x': x + 30 + dx, 'y': y + dy, 'id': 2}]
    cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': points(0, 0)})
    cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': points(30, -20)})
    cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
    page.wait_for_timeout(400)
    assert not close(initial['target'], state(page)['target'])
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(OUTPUT / 'mobile.png'))
    mobile.close()
    browser.close()
print('Camera arrows, keyboard focus, right-drag, Move drag mode, two-finger movement, reset and GIF restoration passed.')
