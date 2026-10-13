import { MOUSE, TOUCH } from 'three';

export function setupCameraControls(scene) {
  const viewport = scene.element;
  const toggle = document.querySelector('#camera-pan-mode');
  const directions = {left: [-1, 0], right: [1, 0], up: [0, 1], down: [0, -1]};
  const move = (direction, scale = 1) => {
    const [x, y] = directions[direction];
    scene.panCamera(x * .045 * scale, y * .045 * scale);
  };
  toggle.onclick = () => {
    if (scene.capturing) return;
    const pan = toggle.getAttribute('aria-pressed') !== 'true';
    toggle.setAttribute('aria-pressed', String(pan));
    scene.controls.mouseButtons.LEFT = pan ? MOUSE.PAN : MOUSE.ROTATE;
    scene.controls.touches.ONE = pan ? TOUCH.PAN : TOUCH.ROTATE;
  };
  viewport.querySelectorAll('[data-pan]').forEach(button => {
    button.onclick = () => move(button.dataset.pan);
  });
  scene.renderer.domElement.addEventListener('pointerdown', () => viewport.focus({preventScroll: true}));
  viewport.addEventListener('keydown', event => {
    if (event.target !== viewport || event.altKey || event.metaKey || event.ctrlKey) return;
    const direction = {ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down'}[event.key];
    if (!direction) return;
    event.preventDefault();
    move(direction, event.shiftKey ? 2 : 1);
  });
}
