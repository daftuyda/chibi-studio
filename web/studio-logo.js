import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { ChibiScene, disposeModel } from './chibi-scene.js';

/** The mascot has its own camera and never changes the character on the stage. */
export function createStudioLogo(element) {
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  let scene, pending, disposed = false, paused = reducedMotion.matches;

  function syncMotion() {
    if (!scene) return;
    scene.playing = scene.blink = scene.controls.autoRotate = !paused;
    if (paused) scene.applyFace(false);
    element.setAttribute('aria-label', `${paused ? 'Play' : 'Pause'} Rice Shower logo animation`);
    element.title = `${paused ? 'Play' : 'Pause'} logo animation`;
  }
  function toggle() { paused = !paused; syncMotion(); }
  function motionPreference() { paused = reducedMotion.matches; syncMotion(); }
  element.addEventListener('click', toggle);
  reducedMotion.addEventListener('change', motionPreference);

  return {
    async setLibrary(models) {
      if (scene || pending || disposed) return;
      const rice = models.find(entry => String(entry.character_id || entry.id) === '1030' && entry.costume === '00');
      if (!rice) { element.hidden = true; return; }
      const request = pending = new AbortController();
      let gltf;
      try {
        const response = await fetch(rice.model_url, {signal: request.signal});
        if (!response.ok) throw new Error('Logo character unavailable');
        gltf = await new GLTFLoader().parseAsync(await response.arrayBuffer(), '');
        if (disposed) { disposeModel(gltf.scene); return; }
        const run = gltf.animations.find(clip => clip.name === 'anm_min_eve_type00_run00_loop');
        if (!run) throw new Error('Logo running animation unavailable');
        gltf.animations = [run];
        scene = new ChibiScene(element);
        scene.setStage({background: 'transparent', platform: false, shadows: false, grid: false, lighting: false});
        scene.renderer.shadowMap.enabled = false;
        scene.setModel(gltf, rice);
        scene.setExpression('smile');
        scene.controls.enabled = false;
        scene.controls.enableDamping = false;
        scene.controls.autoRotateSpeed = 2;
        scene.controls.target.set(0, 1.1, 0);
        scene.camera.position.set(0, 1.35, 4.6);
        scene.controls.update();
        scene.renderer.domElement.setAttribute('aria-hidden', 'true');
        element.disabled = false;
        element.hidden = false;
        element.dataset.model = rice.id;
        element.dataset.animation = run.name;
        element.dataset.ready = 'true';
        scene.resize();
        syncMotion();
      } catch {
        // A missing optional mascot must not prevent the studio from opening.
        if (gltf && scene?.model !== gltf.scene) disposeModel(gltf.scene);
        scene?.dispose();
        scene = null;
        element.hidden = true;
      } finally {
        pending = null;
      }
    },
    dispose() {
      disposed = true;
      pending?.abort();
      element.removeEventListener('click', toggle);
      reducedMotion.removeEventListener('change', motionPreference);
      scene?.dispose();
    },
  };
}
