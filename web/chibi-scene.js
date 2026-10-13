import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { ChibiPhysics } from './chibi-physics.js';

const THEMES = {
  lilac: ['#eeebf7', '#e1d9ed', '#a18abc'], peach: ['#f7eee8', '#ecd7ca', '#bd9483'],
  mint: ['#e9f2ec', '#d6e5d9', '#8aaa97'], night: ['#332e46', '#443b59', '#746580'],
};

export const DEFAULT_STAGE = Object.freeze({
  background: 'solid', color: '#eeebf7', color2: '#d8c8f0', platform: true,
  platformColor: '#e1d9ed', platformSize: 1, shadows: true, grid: false,
  lighting: false, ambient: 1.8, intensity: 2.4, lightColor: '#ffffff', azimuth: 37, elevation: 47,
});

export function disposeModel(root) {
  const geometries = new Set(), materials = new Set(), textures = new Set(), images = new Set();
  root.traverse(object => {
    if (object.geometry) geometries.add(object.geometry);
    for (const material of [object.material].flat().filter(Boolean)) materials.add(material);
    if (object.skeleton?.boneTexture) textures.add(object.skeleton.boneTexture);
  });
  materials.forEach(material => Object.values(material).forEach(value => {
    if (value?.isTexture) textures.add(value);
  }));
  textures.forEach(texture => { if (texture.image?.close) images.add(texture.image); texture.dispose(); });
  images.forEach(image => image.close());
  geometries.forEach(geometry => geometry.dispose());
  materials.forEach(material => material.dispose());
}

/** One renderer and one animation clock for a character preview. */
export class ChibiScene {
  constructor(element, onFrame = () => {}) {
    this.element = element;
    this.onFrame = onFrame;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(34, 1, 0.05, 100);
    this.renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    element.prepend(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.enablePan = true;
    this.controls.screenSpacePanning = true;
    this.controls.minDistance = 2.5;
    this.controls.maxDistance = 10;
    this.controls.maxPolarAngle = Math.PI / 2 + 0.02;
    this.controls.autoRotateSpeed = 0.75;
    this.ambientLight = new THREE.HemisphereLight(0xffffff, 0xd8c8e8, 2.4);
    this.scene.add(this.ambientLight);
    const light = this.keyLight = new THREE.DirectionalLight(0xffffff, 2.4);
    light.position.set(3, 5, 4);
    light.castShadow = true;
    light.shadow.mapSize.set(1024, 1024);
    Object.assign(light.shadow.camera, {left: -3, right: 3, top: 4, bottom: -3, near: 0.1, far: 15});
    light.shadow.bias = -0.0005;
    light.shadow.normalBias = 0.025;
    this.scene.add(light);
    this.floor = new THREE.Mesh(new THREE.CylinderGeometry(1.35, 1.35, 0.07, 96), new THREE.MeshStandardMaterial({roughness: 1}));
    this.floor.position.y = -0.045;
    this.floor.receiveShadow = true;
    this.scene.add(this.floor);
    this.grid = new THREE.GridHelper(20, 40, '#a99cbb', '#a99cbb');
    this.grid.position.y = -0.081;
    this.grid.material.transparent = true;
    this.grid.material.opacity = 0.22;
    this.grid.visible = false;
    this.scene.add(this.grid);
    this.playing = !matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.blink = this.playing;
    this.expression = 'neutral';
    this.physicsEnabled = true;
    this.faceMeshes = [];
    this.faceConfig = {};
    this.blinkClock = 0;
    this.blinkAt = 3.2;
    this.lastTime = performance.now();
    this.inView = true;
    this.stage = {...DEFAULT_STAGE};
    this.materialPairs = [];
    this.backgroundCanvas = document.createElement('canvas');
    this.backgroundTexture = new THREE.CanvasTexture(this.backgroundCanvas);
    this.backgroundTexture.colorSpace = THREE.SRGBColorSpace;
    this.backgroundTexture.minFilter = THREE.LinearFilter;
    this.backgroundImageToken = 0;
    this.setTheme('lilac');
    this.resetCamera();
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(element);
    this.intersectionObserver = new IntersectionObserver(entries => { this.inView = entries[0].isIntersecting; });
    this.intersectionObserver.observe(element);
    this.renderer.setAnimationLoop(() => this.frame());
  }

  resize() {
    if (this.capturing) return;
    const {width, height} = this.element.getBoundingClientRect();
    if (!width || !height) return;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
    this.updateBackground();
  }

  resetCamera() {
    if (this.capturing) return;
    const damping = this.controls.enableDamping, orbit = this.controls.autoRotate;
    this.controls.enableDamping = this.controls.autoRotate = false;
    this.controls.update(); // Finish any pending drag before restoring the view.
    this.camera.position.set(0, 1.4, 5.4);
    this.controls.target.set(0, 1.07, 0);
    this.controls.update();
    this.controls.enableDamping = damping;
    this.controls.autoRotate = orbit;
  }

  panCamera(horizontal, vertical) {
    if (this.capturing || !this.model) return;
    const distance = this.camera.position.distanceTo(this.controls.target);
    const height = 2 * distance * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    this.camera.updateMatrix();
    const offset = new THREE.Vector3().setFromMatrixColumn(this.camera.matrix, 0).multiplyScalar(horizontal * height)
      .addScaledVector(new THREE.Vector3().setFromMatrixColumn(this.camera.matrix, 1), vertical * height);
    this.camera.position.add(offset);
    this.controls.target.add(offset);
    this.controls.update();
  }

  setTheme(name) {
    const theme = THEMES[name] || THEMES.lilac;
    this.setStage({background: 'solid', color: theme[0], platformColor: theme[1]});
    this.grid.material.color.set(theme[2]);
  }

  setStage(changes) {
    for (const key of ['platform', 'shadows', 'grid', 'lighting'])
      if (typeof changes[key] === 'boolean') this.stage[key] = changes[key];
    for (const key of ['color', 'color2', 'platformColor', 'lightColor'])
      if (/^#[\da-f]{6}$/i.test(changes[key])) this.stage[key] = changes[key];
    for (const [key, low, high] of [['platformSize', .6, 1.6], ['ambient', 0, 4], ['intensity', 0, 6], ['azimuth', -180, 180], ['elevation', 10, 85]]) {
      if (changes[key] !== undefined && Number.isFinite(Number(changes[key])))
        this.stage[key] = Math.max(low, Math.min(high, Number(changes[key])));
    }
    if (['solid', 'gradient', 'transparent', 'image'].includes(changes.background)) this.stage.background = changes.background;
    this.floor.visible = this.stage.platform;
    this.floor.scale.set(this.stage.platformSize, 1, this.stage.platformSize);
    this.floor.material.color.set(this.stage.platformColor);
    this.grid.visible = this.stage.grid;
    this.keyLight.castShadow = this.stage.shadows;
    this.keyLight.color.set(this.stage.lightColor);
    this.keyLight.intensity = this.stage.intensity;
    this.ambientLight.intensity = this.stage.ambient;
    const azimuth = THREE.MathUtils.degToRad(this.stage.azimuth), elevation = THREE.MathUtils.degToRad(this.stage.elevation);
    this.keyLight.position.set(6 * Math.cos(elevation) * Math.sin(azimuth), 6 * Math.sin(elevation), 6 * Math.cos(elevation) * Math.cos(azimuth));
    for (const {object, original, lit} of this.materialPairs) object.material = this.stage.lighting ? lit : original;
    this.updateBackground();
  }

  updateBackground() {
    const {background, color, color2} = this.stage;
    this.element.dataset.background = background;
    if (background === 'transparent') { this.scene.background = null; return; }
    if (background === 'solid' || (background === 'image' && !this.backgroundImage)) {
      this.scene.background = new THREE.Color(color); return;
    }
    const canvas = this.backgroundCanvas;
    canvas.width = Math.max(1, Math.round(512 * (this.camera.aspect || 1)));
    canvas.height = 512;
    const context = canvas.getContext('2d');
    if (background === 'image') {
      const image = this.backgroundImage, scale = Math.max(canvas.width / image.width, canvas.height / image.height);
      context.fillStyle = color; context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, (canvas.width - image.width * scale) / 2, (canvas.height - image.height * scale) / 2, image.width * scale, image.height * scale);
    } else {
      const gradient = context.createLinearGradient(0, 0, 0, canvas.height);
      gradient.addColorStop(0, color); gradient.addColorStop(1, color2);
      context.fillStyle = gradient; context.fillRect(0, 0, canvas.width, canvas.height);
    }
    this.backgroundTexture.needsUpdate = true;
    this.scene.background = this.backgroundTexture;
  }

  async setBackgroundImage(file) {
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 20 * 1024 * 1024)
      throw new Error('Choose a PNG, JPEG or WebP image under 20 MB.');
    const token = ++this.backgroundImageToken;
    const image = await createImageBitmap(file);
    if (token !== this.backgroundImageToken) { image.close(); return false; }
    if (image.width > 8192 || image.height > 8192) { image.close(); throw new Error('Please use a background no larger than 8192 pixels on either side.'); }
    this.backgroundImage?.close();
    this.backgroundImage = image;
    this.setStage({background: 'image'});
    return true;
  }

  setModel(gltf, metadata = {}) {
    const model = gltf.scene;
    const mixer = new THREE.AnimationMixer(model);
    const clips = gltf.animations || [];
    const actions = new Array(clips.length);
    const initialIndex = Math.max(0, clips.findIndex(clip => /idle/i.test(clip.name)));
    if (clips[initialIndex]) actions[initialIndex] = mixer.clipAction(clips[initialIndex]);
    actions[initialIndex]?.play();
    mixer.update(0);
    model.updateMatrixWorld(true);
    // Measure the animated pose, since the rig's rest pose can have a different foot height.
    const box = new THREE.Box3().setFromObject(model, true);
    const size = box.getSize(new THREE.Vector3());
    if (![size.x, size.y, size.z].every(Number.isFinite) || size.y < 0.0001) {
      mixer.stopAllAction();
      mixer.uncacheRoot(model);
      disposeModel(model);
      throw new Error('This file has no visible character geometry.');
    }
    this.clearModel();
    this.model = model;
    this.mixer = mixer;
    this.clips = clips;
    this.actions = actions;
    this.action = actions[initialIndex];
    this.clipIndex = initialIndex;
    this.actor = new THREE.Group();
    this.actor.add(model);
    this.scene.add(this.actor);
    const scale = 2.15 / size.y;
    this.actor.scale.setScalar(scale);
    this.actor.position.set(-(box.min.x + box.max.x) * 0.5 * scale, -box.min.y * scale, -(box.min.z + box.max.z) * 0.5 * scale);
    this.actor.updateMatrixWorld(true);
    this.physics = new ChibiPhysics(model, metadata.physics || gltf.userData?.umaPhysics);
    this.physicsActions = [];
    this.faceConfig = metadata.faces || gltf.userData?.umaFaces || {};
    this.faceMeshes = [];
    const geometryUses = new Map();
    model.traverse(object => { if (object.isMesh) geometryUses.set(object.geometry, (geometryUses.get(object.geometry) || 0) + 1); });
    let meshes = 0, triangles = 0, bones = 0;
    this.model.traverse(object => {
      if (object.isBone) bones++;
      if (!object.isMesh) return;
      meshes++;
      triangles += (object.geometry.index?.count || object.geometry.attributes.position.count) / 3;
      object.castShadow = true;
      object.frustumCulled = false; // Bounds of a skinned mesh change as the clip plays.
      for (const material of [object.material].flat()) {
        material.toneMapped = false;
        if (material.transparent) material.depthWrite = false;
      }
      const face = this.faceConfig.meshes?.[object.name];
      if (face && ['eyes', 'mouth', 'brows'].includes(face.part) && object.geometry.attributes.uv) {
        const uses = geometryUses.get(object.geometry);
        if (uses > 1) {
          geometryUses.set(object.geometry, uses - 1);
          object.geometry = object.geometry.clone();
        }
        const uv = object.geometry.attributes.uv;
        this.faceMeshes.push({object, face, base: uv.array.slice()});
        object.castShadow = false;
        for (const material of [object.material].flat()) {
          material.polygonOffset = true;
          material.polygonOffsetFactor = -1;
          material.polygonOffsetUnits = -1;
        }
      }
    });
    const converted = new Map();
    this.model.traverse(object => {
      if (!object.isMesh) return;
      const original = object.material;
      const lit = [original].flat().map(source => {
        if (converted.has(source)) return converted.get(source);
        const material = source.isMeshBasicMaterial ? new THREE.MeshStandardMaterial({
          name: source.name, map: source.map, color: source.color, opacity: source.opacity,
          transparent: source.transparent, alphaTest: source.alphaTest, side: source.side,
          depthWrite: source.depthWrite, depthTest: source.depthTest, vertexColors: source.vertexColors,
          polygonOffset: source.polygonOffset, polygonOffsetFactor: source.polygonOffsetFactor,
          polygonOffsetUnits: source.polygonOffsetUnits, roughness: 1, metalness: 0, toneMapped: false,
        }) : source;
        if (material !== source && (this.faceConfig.meshes?.[object.name] || ['M_Face', 'M_Cheek'].includes(object.name))) {
          // Face atlases include painted skin. Share a head-facing normal across
          // the face and decals so their lighting does not reveal patch edges.
          material.onBeforeCompile = shader => {
            shader.vertexShader = shader.vertexShader.replace('#include <beginnormal_vertex>',
              '#include <beginnormal_vertex>\nobjectNormal = vec3(0.0, 0.0, -1.0);');
          };
          material.customProgramCacheKey = () => 'chibi-face-lighting-v1';
        }
        converted.set(source, material);
        return material;
      });
      this.materialPairs.push({object, original, lit: Array.isArray(original) ? lit : lit[0]});
    });
    this.setStage({});
    this.expression = 'neutral';
    this.blinkClock = 0;
    this.eyesClosed = false;
    this.setExpression('neutral');
    this.playClip(initialIndex, false);
    this.resetCamera();
    return {meshes, triangles: Math.round(triangles), bones, animations: this.clips.length, faceControls: this.faceMeshes.length > 0, physics: this.physics.available};
  }

  playClip(index, fade = true) {
    if (!this.clips?.[index]) return;
    let next = this.actions[index] ||= this.mixer.clipAction(this.clips[index]);
    if (this.physicsEnabled && this.physics?.available) {
      if (!this.physicsActions[index]) this.physicsActions[index] = this.mixer.clipAction(this.physics.clip(this.clips[index]));
      next = this.physicsActions[index];
    }
    const previous = this.action;
    next.reset().setEffectiveTimeScale(1).setEffectiveWeight(1).play();
    if (previous && previous !== next) {
      if (fade && this.playing) next.crossFadeFrom(previous, 0.2, false);
      else previous.stop();
    }
    this.action = next;
    this.clipIndex = index;
    this.mixer.update(0);
  }

  seek(fraction) {
    if (!this.action) return;
    [...this.actions, ...this.physicsActions].forEach(action => { if (action && action !== this.action) action.stop(); });
    this.action.stopFading().setEffectiveWeight(1);
    this.action.time = Math.max(0, Math.min(1, fraction)) * this.action.getClip().duration;
    this.mixer.update(0);
  }

  setExpression(name) {
    this.expression = name;
    this.applyFace(false);
  }

  setPhysics(enabled) {
    this.physicsEnabled = enabled;
    const time = this.action?.time || 0, duration = this.action?.getClip().duration || 1;
    this.playClip(this.clipIndex, false);
    this.seek(time / duration);
  }

  applyFace(closed) {
    const preset = this.faceConfig.presets?.[this.expression] || {};
    for (const {object, face, base} of this.faceMeshes) {
      const cols = Math.max(1, Math.min(64, Number(face.columns) || 4));
      const rows = Math.max(1, Math.min(64, Number(face.rows) || 8));
      const chosen = closed && face.part === 'eyes' ? (this.faceConfig.blink ?? 8) : (preset[face.part] ?? 0);
      const frame = Math.max(0, Math.min(cols * rows - 1, Math.floor(Number(chosen) || 0)));
      const offsetX = (frame % cols) / cols;
      const offsetY = (face.flip_v ? 1 : -1) * Math.floor(frame / cols) / rows;
      const uv = object.geometry.attributes.uv;
      for (let i = 0; i < uv.count; i++) uv.setXY(i, base[i * 2] + offsetX, base[i * 2 + 1] + offsetY);
      uv.needsUpdate = true;
    }
  }

  frame() {
    const now = performance.now(), delta = Math.min((now - this.lastTime) / 1000, 0.05);
    this.lastTime = now;
    if (this.capturing || document.hidden || !this.inView) return;
    if (this.playing) this.mixer?.update(delta * (this.speed || 1));
    if (this.faceMeshes.length) {
      this.blinkClock += delta;
      const closed = this.blink && this.blinkClock >= this.blinkAt && this.blinkClock < this.blinkAt + 0.12;
      if (this.blinkClock > this.blinkAt + 0.12) { this.blinkClock = 0; this.blinkAt = 2.8 + Math.random() * 2; }
      if (closed !== this.eyesClosed) { this.eyesClosed = closed; this.applyFace(closed); }
    }
    this.controls.update(delta);
    this.renderer.render(this.scene, this.camera);
    this.onFrame({time: this.action?.time || 0, duration: this.action?.getClip().duration || 0});
  }

  screenshot() {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL('image/png');
  }

  /** Deterministic frames; export speed does not depend on playback or tab visibility. */
  beginCapture(width, height, orbit = false) {
    if (this.capturing || !this.action) throw new Error('Choose an animated character first.');
    const saved = {time: this.action.time, camera: this.camera.position.clone(), rotation: this.camera.quaternion.clone(),
      ratio: this.renderer.getPixelRatio(), size: this.renderer.getSize(new THREE.Vector2()), aspect: this.camera.aspect,
      closed: this.eyesClosed, enabled: this.controls.enabled};
    const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
    const context = canvas.getContext('2d', {willReadFrequently: true});
    if (!context) throw new Error('This browser could not prepare the GIF frames.');
    const offset = saved.camera.clone().sub(this.controls.target);
    const duration = this.action.getClip().duration;
    this.capturing = true;
    this.controls.enabled = false;
    let restored = false;
    const restore = () => {
      if (restored) return;
      restored = true;
      if (this.disposed) { this.capturing = false; return; }
      this.renderer.setPixelRatio(saved.ratio); this.renderer.setSize(saved.size.x, saved.size.y, false);
      this.camera.position.copy(saved.camera); this.camera.quaternion.copy(saved.rotation);
      this.camera.aspect = saved.aspect; this.camera.updateProjectionMatrix();
      this.seek(saved.time / duration); this.applyFace(saved.closed);
      this.controls.enabled = saved.enabled;
      this.capturing = false; this.lastTime = performance.now();
      this.resize();
      this.renderer.render(this.scene, this.camera);
    };
    try {
      this.renderer.setPixelRatio(1); this.renderer.setSize(width, height, false);
      this.camera.aspect = width / height; this.camera.updateProjectionMatrix(); this.updateBackground();
    } catch (error) { restore(); throw error; }
    return {
      render: (seconds, fraction) => {
        this.seek(((seconds * (this.speed || 1)) % duration) / duration);
        this.applyFace(this.blink && seconds % 3.6 >= 3.48);
        if (orbit) {
          this.camera.position.copy(offset).applyAxisAngle(new THREE.Vector3(0, 1, 0), fraction * Math.PI * 2).add(this.controls.target);
          this.camera.lookAt(this.controls.target);
        }
        this.renderer.render(this.scene, this.camera);
        context.clearRect(0, 0, width, height);
        context.drawImage(this.renderer.domElement, 0, 0);
        return context.getImageData(0, 0, width, height).data;
      },
      restore,
    };
  }

  clearModel() {
    const extraMaterials = new Set();
    for (const {object, original, lit} of this.materialPairs) {
      object.material = original;
      [lit].flat().forEach(material => { if (![original].flat().includes(material)) extraMaterials.add(material); });
    }
    extraMaterials.forEach(material => material.dispose());
    this.materialPairs = [];
    if (this.mixer) {
      this.mixer.stopAllAction();
      this.mixer.uncacheRoot(this.model);
    }
    if (this.actor) this.scene.remove(this.actor);
    if (this.model) disposeModel(this.model);
    this.actor = this.model = this.mixer = this.action = null;
    this.clips = this.actions = [];
    this.physicsActions = []; this.physics = null;
    this.faceMeshes = [];
  }

  dispose() {
    this.disposed = true;
    this.backgroundImageToken++;
    this.backgroundImage?.close();
    this.backgroundTexture.dispose();
    this.renderer.setAnimationLoop(null);
    this.resizeObserver.disconnect();
    this.intersectionObserver.disconnect();
    this.controls.dispose();
    this.clearModel();
    disposeModel(this.scene);
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
