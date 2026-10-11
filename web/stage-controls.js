import { DEFAULT_STAGE } from './chibi-scene.js';

export function setupStageControls(scene, onError) {
  const $ = selector => document.querySelector(selector);
  const fields = {
    'background-mode': 'background', 'background-color': 'color', 'background-color-2': 'color2',
    'show-platform': 'platform', 'platform-color': 'platformColor', 'platform-size': 'platformSize',
    'show-grid': 'grid', 'show-shadows': 'shadows', 'studio-lighting': 'lighting',
    'ambient-light': 'ambient', 'key-light': 'intensity', 'light-color': 'lightColor',
    'light-direction': 'azimuth', 'light-height': 'elevation',
  };
  const save = () => {
    try { localStorage.setItem('chibi-stage-v1', JSON.stringify({...scene.stage, background: scene.stage.background === 'image' ? 'solid' : scene.stage.background})); } catch { }
  };
  const sync = () => {
    for (const [id, key] of Object.entries(fields)) {
      const field = $(`#${id}`);
      if (field.type === 'checkbox') field.checked = scene.stage[key]; else field.value = scene.stage[key];
      const output = $(`output[for="${id}"]`);
      if (output) output.value = `${scene.stage[key]}${id === 'light-direction' || id === 'light-height' ? '°' : ''}`;
    }
    $('#background-colors').hidden = scene.stage.background === 'transparent';
    $('#gradient-color').hidden = scene.stage.background !== 'gradient';
    $('#background-image-field').hidden = scene.stage.background !== 'image';
    $('#lighting-controls').hidden = !scene.stage.lighting;
    $('#platform-controls').hidden = !scene.stage.platform;
    $('#background-image-note').textContent = scene.backgroundImage ? 'Image stays in this browser session.' : 'Choose an image from your computer.';
  };
  try {
    const saved = JSON.parse(localStorage.getItem('chibi-stage-v1'));
    if (saved && typeof saved === 'object') scene.setStage(saved);
  } catch { }
  for (const [id, key] of Object.entries(fields)) {
    const field = $(`#${id}`);
    field.addEventListener('input', () => {
      scene.setStage({[key]: field.type === 'checkbox' ? field.checked : field.value});
      sync(); save();
    });
  }
  document.querySelectorAll('button[data-theme]').forEach(button => button.onclick = () => {
    scene.setTheme(button.dataset.theme); document.body.dataset.theme = button.dataset.theme;
    document.querySelectorAll('button[data-theme]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    sync(); save();
  });
  $('#background-image').onchange = async event => {
    const file = event.target.files[0]; event.target.value = '';
    if (!file) return;
    try { if (await scene.setBackgroundImage(file)) { sync(); save(); $('#message').hidden = true; } }
    catch (error) { onError(error.message || 'This image could not be opened.'); }
  };
  $('#reset-stage').onclick = () => {
    scene.backgroundImageToken++; scene.backgroundImage?.close(); scene.backgroundImage = null;
    scene.setStage(DEFAULT_STAGE); document.body.dataset.theme = 'lilac';
    document.querySelectorAll('button[data-theme]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.theme === 'lilac')));
    sync(); save();
  };
  sync();
}
