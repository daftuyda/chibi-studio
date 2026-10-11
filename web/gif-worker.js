import { GIFEncoder, quantize, applyPalette } from './vendor/gifenc/gifenc.js';

let encoder, width, height, transparent;
self.onmessage = ({data}) => {
  try {
    if (data.type === 'start') {
      ({width, height, transparent} = data);
      encoder = GIFEncoder();
    } else if (data.type === 'frame') {
      const rgba = new Uint8Array(data.rgba);
      const palette = quantize(rgba, transparent ? 255 : 256);
      const indexed = applyPalette(rgba, palette);
      if (transparent) {
        // Reserve index zero in EVERY palette, including the logical-screen
        // background. Disposal then clears previous frames without trails.
        palette.unshift([0, 0, 0]);
        for (let i = 0; i < indexed.length; i++) indexed[i] = rgba[i * 4 + 3] < 128 ? 0 : indexed[i] + 1;
      }
      encoder.writeFrame(indexed, width, height, {palette, delay: data.delay, repeat: 0,
        transparent, transparentIndex: 0, dispose: transparent ? 2 : 1});
    } else if (data.type === 'finish') {
      encoder.finish();
      const bytes = encoder.bytes();
      self.postMessage({type: 'finished', bytes: bytes.buffer}, [bytes.buffer]);
      encoder = null;
      return;
    } else throw new Error('Unknown GIF operation.');
    self.postMessage({type: 'ready'});
  } catch (error) { self.postMessage({type: 'error', message: error.message || 'GIF encoding failed.'}); }
};
