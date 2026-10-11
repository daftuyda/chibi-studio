export function gifSettings(scene, {size, shape, fps, duration, orbit}) {
  if (!scene.action) throw new Error('Choose an animated character first.');
  size = Number(size); fps = Number(fps);
  if (![256, 512, 768].includes(size) || ![10, 20, 25].includes(fps)) throw new Error('Choose a supported GIF size and frame rate.');
  const aspect = {square: 1, portrait: .75, wide: 4 / 3}[shape];
  if (!aspect) throw new Error('Choose a GIF shape.');
  const seconds = duration === 'loop' ? scene.action.getClip().duration / (scene.speed || 1) : Number(duration);
  if (!Number.isFinite(seconds) || seconds < .1 || seconds > 20)
    throw new Error('Choose a duration up to 20 seconds. This animation is too long for one complete cycle.');
  const width = Math.round(size * Math.min(1, aspect)), height = Math.round(size / Math.max(1, aspect));
  const frames = Math.max(2, Math.round(seconds * fps));
  return {width, height, frames, seconds, orbit: Boolean(orbit), transparent: scene.stage.background === 'transparent'};
}

export async function createGif(scene, settings, {signal, progress = () => {}} = {}) {
  const options = gifSettings(scene, settings);
  signal?.throwIfAborted();
  const worker = new Worker(new URL('./gif-worker.js', import.meta.url), {type: 'module'});
  let rejectPending = null, capture = null;
  const abortError = () => new DOMException('Export cancelled.', 'AbortError');
  const abort = () => rejectPending?.(abortError());
  signal?.addEventListener('abort', abort, {once: true});
  const request = (message, transfer = []) => new Promise((resolve, reject) => {
    let timeout;
    const finish = (error, value) => {
      clearTimeout(timeout); rejectPending = null;
      worker.onmessage = worker.onerror = worker.onmessageerror = null;
      if (error) reject(error); else resolve(value);
    };
    rejectPending = error => finish(error);
    timeout = setTimeout(() => finish(new Error('GIF encoding timed out. Try a smaller image or shorter duration.')), 30000);
    worker.onmessage = ({data}) => finish(data.type === 'error' ? new Error(data.message) : null, data);
    worker.onerror = event => { event.preventDefault(); finish(new Error('The GIF encoder could not run. Reload the viewer and try again.')); };
    worker.onmessageerror = () => finish(new Error('The browser could not read an encoded frame.'));
    if (signal?.aborted) { finish(abortError()); return; }
    try { worker.postMessage(message, transfer); } catch (error) { finish(error); }
  });
  try {
    await request({type: 'start', ...options});
    capture = scene.beginCapture(options.width, options.height, options.orbit);
    for (let frame = 0; frame < options.frames; frame++) {
      signal?.throwIfAborted();
      const rgba = capture.render(frame * options.seconds / options.frames, frame / options.frames);
      // GIF delays use hundredths of a second; distribute rounding so the total
      // duration stays correct at 25 fps and for non-integer animation cycles.
      const delay = (Math.round((frame + 1) * options.seconds * 100 / options.frames) - Math.round(frame * options.seconds * 100 / options.frames)) * 10;
      await request({type: 'frame', rgba: rgba.buffer, delay}, [rgba.buffer]);
      progress((frame + 1) / options.frames, frame + 1, options.frames);
    }
    const result = await request({type: 'finish'});
    return {blob: new Blob([result.bytes], {type: 'image/gif'}), ...options};
  } finally {
    worker.terminate();
    signal?.removeEventListener('abort', abort);
    capture?.restore();
  }
}
