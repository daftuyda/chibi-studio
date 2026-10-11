import { createGif, gifSettings } from './gif-export.js';

export function setupGifControls(scene, getName) {
  const $ = selector => document.querySelector(selector), dialog = $('#gif-dialog');
  let controller, resultUrl;
  const settings = () => ({size: $('#gif-size').value, shape: $('#gif-shape').value, fps: $('#gif-fps').value,
    duration: $('#gif-duration').value, orbit: $('#gif-orbit').checked});
  const estimate = () => {
    try {
      const options = gifSettings(scene, settings());
      $('#gif-estimate').textContent = `${options.width} × ${options.height} · ${options.frames} frames · ${options.seconds.toFixed(2)} seconds`;
      $('#gif-transparency-note').hidden = !options.transparent;
      $('#gif-start').disabled = false;
    } catch (error) { $('#gif-estimate').textContent = error.message; $('#gif-start').disabled = true; }
  };
  const clearResult = () => {
    $('#gif-result').hidden = true;
    $('#gif-preview').removeAttribute('src'); $('#gif-download').removeAttribute('href');
    if (resultUrl) URL.revokeObjectURL(resultUrl); resultUrl = null;
  };
  $('#save-gif').onclick = () => {
    clearResult(); $('#gif-status').textContent = 'Uses your current outfit, expression, stage and camera angle.';
    $('#gif-progress').hidden = true; estimate(); dialog.showModal();
  };
  $('#gif-settings').oninput = estimate;
  $('#gif-form').onsubmit = async event => {
    event.preventDefault();
    if (controller) return;
    clearResult();
    controller = new AbortController();
    $('#gif-settings').disabled = true; $('#gif-start').disabled = true; $('#gif-cancel').hidden = false;
    $('#gif-progress').value = 0; $('#gif-progress').hidden = false;
    $('#gif-status').textContent = 'Preparing your GIF…';
    dialog.dataset.state = 'exporting';
    try {
      const result = await createGif(scene, settings(), {signal: controller.signal, progress: (fraction, frame, total) => {
        $('#gif-progress').value = fraction; $('#gif-status').textContent = `Creating frame ${frame} of ${total}…`;
      }});
      resultUrl = URL.createObjectURL(result.blob);
      $('#gif-preview').src = resultUrl;
      $('#gif-download').href = resultUrl;
      $('#gif-download').download = `${getName().replace(/[^\w-]+/g, '-').toLowerCase()}.gif`;
      $('#gif-result').hidden = false;
      $('#gif-status').textContent = `Ready · ${result.width} × ${result.height} · ${(result.blob.size / 1048576).toFixed(2)} MB`;
      dialog.dataset.state = 'ready';
    } catch (error) {
      $('#gif-status').textContent = error.name === 'AbortError' ? 'Export cancelled. Your stage is ready to use.' : error.message;
      dialog.dataset.state = error.name === 'AbortError' ? 'cancelled' : 'error';
    } finally {
      controller = null; $('#gif-settings').disabled = false; $('#gif-start').disabled = false;
      $('#gif-cancel').hidden = true; $('#gif-progress').hidden = true;
    }
  };
  $('#gif-cancel').onclick = () => controller?.abort();
  $('#gif-close').onclick = () => { controller?.abort(); dialog.close(); };
  dialog.oncancel = event => { if (controller) { event.preventDefault(); controller.abort(); } };
  window.addEventListener('pagehide', () => { controller?.abort(); if (resultUrl) URL.revokeObjectURL(resultUrl); });
}
