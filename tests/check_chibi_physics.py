"""Check real Tachyon sleeve tracks, stable loops and optional physics in Chrome."""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.environ.get('CHIBI_STUDIO_URL', 'http://127.0.0.1:8084').rstrip('/')
OUTPUT = Path(__file__).resolve().parents[1] / '.local/chibi-physics-check'
OUTPUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1100}, reduced_motion='reduce')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(URL + '/chibi')
    page.wait_for_function("document.querySelector('#status').dataset.state === 'ready'")
    result = page.evaluate('''async () => {
      const {GLTFLoader} = await import('three/addons/loaders/GLTFLoader.js');
      const {ChibiPhysics} = await import('/assets/chibi-physics.js');
      const response = await fetch('/chibi-models/1032/model.glb');
      const gltf = await new GLTFLoader().parseAsync(await response.arrayBuffer(), '');
      const physics = new ChibiPhysics(gltf.scene, gltf.userData.umaPhysics);
      if (!physics.available) throw new Error('Tachyon cloth metadata is missing');
      const clip = gltf.animations.find(clip => clip.name.endsWith('1032_00_res01_loop'));
      const start = performance.now(), baked = physics.clip(clip);
      if (physics.clip(clip) !== baked) throw new Error('Repeat selection should reuse the solved clip');
      const sleeves = baked.tracks.filter(track => /Sleeve.*quaternion/.test(track.name));
      const changing = sleeves.filter(track => track.values.some((value, i) => Math.abs(value - track.values[i % 4]) > .02));
      if (changing.length < 2) throw new Error('Both sleeves must have secondary motion');
      for (const track of baked.tracks) {
        if (!track.values.every(Number.isFinite)) throw new Error('Non-finite spring transform');
        if (!/quaternion$/.test(track.name)) continue;
        for (let i = 0; i < track.values.length; i += 4) {
          const magnitude = Math.hypot(...track.values.slice(i, i + 4));
          if (Math.abs(magnitude - 1) > .002) throw new Error('Invalid bone rotation');
        }
      }
      for (const name of ['Arm_L.quaternion', 'Arm_R.quaternion', 'Elbow_L.quaternion', 'Elbow_R.quaternion']) {
        if (baked.tracks.find(track => track.name === name) !== clip.tracks.find(track => track.name === name))
          throw new Error('Physics must preserve the original arm motion');
      }
      for (const track of changing) {
        const first = track.values.slice(0, 4), last = track.values.slice(-4);
        if (Math.abs(Math.abs(first.reduce((sum, value, i) => sum + value * last[i], 0)) - 1) > .001)
          throw new Error('Sleeve loop has a seam');
      }
      return {chains: physics.chains.length, movingSleeveBones: changing.length, calculationMs: Math.round(performance.now() - start)};
    }''')
    page.locator('#character').select_option('1032')
    page.wait_for_function("document.querySelector('#viewport').dataset.model === '1032'")
    page.locator('#animation').select_option(label='Character pose 00 res01')
    page.locator('#timeline').evaluate('el => { el.value = .4; el.dispatchEvent(new Event("input")); }')
    assert not page.locator('#cloth-physics').is_disabled()
    canvas = page.locator('#viewport canvas')
    enabled = canvas.screenshot()
    page.locator('#cloth-physics').uncheck()
    assert canvas.screenshot() != enabled, 'Sleeve physics must visibly affect the actual rig.'
    page.locator('#cloth-physics').check()
    assert canvas.screenshot() == enabled, 'Re-enabling physics at the same time must produce the same pose.'
    page.locator('#studio-lighting').check()
    for expression in ['neutral', 'laughing', 'angry', 'excited']:
        page.locator(f'[data-expression={expression}]').click()
        page.locator('.stage-card').screenshot(path=OUTPUT / f'tachyon-{expression}.png')
    assert not errors, errors
    print('Tachyon physics passed:', result)
    browser.close()
