import * as THREE from 'three';

const clamp = THREE.MathUtils.clamp;
const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const vector = value => new THREE.Vector3(number(value?.x), number(value?.y), -number(value?.z));
const array = value => Array.isArray(value) ? value : [];
const v1 = new THREE.Vector3(), v2 = new THREE.Vector3(), v3 = new THREE.Vector3();
const rotation = new THREE.Quaternion(), parentRotation = new THREE.Quaternion();

/** Bounded spring bones using the outfit's original cloth data. Solving once
 * per clip at 60 Hz keeps scrubbing, slow playback and GIFs repeatable. This is
 * a browser approximation, not the game's native cloth simulation.
 */
export class ChibiPhysics {
  constructor(model, metadata) {
    this.model = model;
    this.chains = [];
    this.bones = new Set();
    this.colliders = new Map();
    const named = new Map();
    model.traverse(object => { if (!named.has(object.name)) named.set(object.name, object); });
    const sources = metadata?.version === 1 ? array(metadata.sources).slice(0, 12).filter(source => source?.data) : [];
    for (const {data} of sources) {
      for (const collider of array(data?.collisionParam).slice(0, 256).filter(Boolean)) {
        const bone = named.get(collider._targetObjectName);
        if (!bone || collider._isInner || ![0, 2].includes(collider._type)) continue;
        this.colliders.set(collider._collisionName, {bone, local: vector(collider._offset),
          local2: vector(collider._type === 2 ? collider._offset2 : collider._offset),
          radius: Math.max(0, number(collider._radius)), a: new THREE.Vector3(), b: new THREE.Vector3(), size: 0});
      }
    }
    for (const {data} of sources) {
      for (const root of array(data?.springParam).slice(0, 256).filter(Boolean)) {
        const base = named.get(root._boneName);
        if (!base || !base.isBone || this.bones.has(base)) continue;
        const params = new Map([root, ...array(root._childElements)].filter(Boolean).map(value => [value._boneName, value]));
        const points = [];
        let bone = base;
        // Resolve declared linear chains only; never guess ordinary arm or leg joints.
        while (bone && points.length < 32) {
          points.push({bone, config: params.get(bone.name) || root, target: new THREE.Vector3(),
            position: new THREE.Vector3(), previous: new THREE.Vector3()});
          const children = bone.children.filter(child => child.isBone && params.has(child.name));
          bone = children.length === 1 ? children[0] : null;
        }
        if (points.length < 2) continue;
        points.slice(0, -1).forEach(point => this.bones.add(point.bone));
        this.chains.push(points);
      }
    }
    this.rest = new Map([...this.bones].map(bone => [bone, bone.quaternion.clone()]));
    this.cache = new Map();
  }

  get available() { return this.chains.length > 0; }

  prepare(reset = false) {
    this.model.updateMatrixWorld(true);
    for (const collider of this.colliders.values()) {
      collider.a.copy(collider.local).applyMatrix4(collider.bone.matrixWorld);
      collider.b.copy(collider.local2).applyMatrix4(collider.bone.matrixWorld);
      collider.size = collider.radius * Math.abs(collider.bone.getWorldScale(v1).x);
    }
    for (const chain of this.chains) for (const point of chain) {
      point.bone.getWorldPosition(point.target);
      if (reset) { point.position.copy(point.target); point.previous.copy(point.target); }
    }
  }

  step(dt) {
    this.prepare();
    for (const chain of this.chains) {
      chain[0].position.copy(chain[0].target);
      const scale = Math.abs(chain[0].bone.getWorldScale(v1).x);
      for (let i = 1; i < chain.length; i++) {
        const point = chain[i], parent = chain[i - 1], config = parent.config;
        const axis = v1.subVectors(point.target, parent.target).clone();
        const length = axis.length();
        if (length < 1e-7) { point.position.copy(parent.position); continue; }
        if (i > 1) {
          v2.subVectors(parent.target, chain[i - 2].target).normalize();
          v3.subVectors(parent.position, chain[i - 2].position).normalize();
          axis.applyQuaternion(rotation.setFromUnitVectors(v2, v3));
        }
        const goal = axis.clone().add(parent.position);
        const damping = Math.exp(-clamp(number(config._dragForce, 800) * .008, .5, 25) * dt);
        const stiffness = clamp(number(config._stiffnessForce, 100) * .25, 5, 1000);
        const previous = point.position.clone();
        point.position.addScaledVector(v1.subVectors(point.position, point.previous), damping);
        point.position.addScaledVector(v1.subVectors(goal, point.position), stiffness * dt * dt);
        point.position.y -= clamp(number(config._gravity) * .002, -16, 16) * scale * dt * dt;
        point.previous.copy(previous);

        const direction = v1.subVectors(point.position, parent.position).normalize();
        const rest = v2.copy(axis).normalize();
        const angle = Math.acos(clamp(rest.dot(direction), -1, 1));
        const limits = [config._limitAngleMin, config._limitAngleMax].flatMap(value => [value?.x, value?.y, value?.z]);
        const limit = config._isLimit ? THREE.MathUtils.degToRad(clamp(Math.max(...limits.map(value => Math.abs(number(value)))), 5, 120)) : Math.PI;
        if (angle > limit) {
          rotation.setFromUnitVectors(rest, direction).slerp(new THREE.Quaternion(), 1 - limit / angle);
          direction.copy(rest).applyQuaternion(rotation);
        }
        point.position.copy(parent.position).addScaledVector(direction, length);
        for (const name of array(config._collisionNameList)) {
          const collider = this.colliders.get(name);
          if (!collider) continue;
          const segment = v1.subVectors(collider.b, collider.a);
          const t = clamp(v2.subVectors(point.position, collider.a).dot(segment) / (segment.lengthSq() || 1), 0, 1);
          const closest = v2.copy(collider.a).addScaledVector(segment, t);
          const normal = v3.subVectors(point.position, closest);
          const radius = collider.size + Math.max(0, number(config._collisionRadius)) * scale;
          if (normal.lengthSq() < radius * radius && normal.lengthSq() > 1e-10) {
            point.position.copy(closest).addScaledVector(normal.normalize(), radius);
            v1.subVectors(point.position, parent.position).normalize();
            point.position.copy(parent.position).addScaledVector(v1, length);
          }
        }
      }
      for (let i = 0; i < chain.length - 1; i++) {
        const bone = chain[i].bone, child = chain[i + 1];
        const origin = bone.getWorldPosition(new THREE.Vector3());
        const from = child.bone.getWorldPosition(v1).sub(origin).normalize();
        const to = v2.subVectors(child.position, origin).normalize();
        if (from.lengthSq() < .5 || to.lengthSq() < .5) continue;
        const current = bone.getWorldQuaternion(new THREE.Quaternion());
        rotation.setFromUnitVectors(from, to).multiply(current);
        bone.parent.getWorldQuaternion(parentRotation).invert();
        bone.quaternion.copy(parentRotation.multiply(rotation));
        bone.updateMatrixWorld(true);
      }
    }
  }

  clip(original) {
    if (!this.available || !Number.isFinite(original.duration) || original.duration <= 0 || original.duration > 30) return original;
    if (this.cache.has(original)) return this.cache.get(original);
    const saved = [];
    this.model.traverse(object => saved.push([object, object.position.clone(), object.quaternion.clone(), object.scale.clone()]));
    const bindings = original.tracks.map(track => ({sample: track.createInterpolant(), binding: THREE.PropertyBinding.create(this.model, track.name)}));
    const sample = time => {
      this.rest.forEach((value, bone) => bone.quaternion.copy(value));
      bindings.forEach(({sample, binding}) => binding.setValue(sample.evaluate(time), 0));
    };
    const steps = Math.max(2, Math.ceil(original.duration * 60)), dt = original.duration / steps;
    const bones = [...this.bones], values = bones.map(() => new Float32Array((steps + 1) * 4));
    const times = Float32Array.from({length: steps + 1}, (_, i) => dt * i);
    try {
      sample(0); this.prepare(true);
      for (let frame = 0; frame < steps * 2; frame++) {
        sample((frame % steps) * dt); this.step(dt);
      }
      for (let frame = 0; frame <= steps; frame++) {
        sample((frame % steps) * dt); this.step(dt);
        bones.forEach((bone, i) => bone.quaternion.toArray(values[i], frame * 4));
      }
      const tracks = original.tracks.filter(track => !bones.some(bone => track.name === `${bone.name}.quaternion` || track.name === `${bone.uuid}.quaternion`));
      bones.forEach((bone, i) => {
        if (/_loop$/.test(original.name)) {
          const first = new THREE.Quaternion().fromArray(values[i], 0);
          const blend = Math.min(8, Math.floor(steps / 5));
          for (let f = steps - blend; f <= steps; f++) {
            const amount = (f - (steps - blend)) / (blend || 1);
            rotation.fromArray(values[i], f * 4).slerp(first, amount * amount).toArray(values[i], f * 4);
          }
        }
        tracks.push(new THREE.QuaternionKeyframeTrack(`${bone.name}.quaternion`, times, values[i]));
      });
      const clip = new THREE.AnimationClip(original.name, original.duration, tracks);
      this.cache.set(original, clip);
      return clip;
    } finally {
      bindings.forEach(({binding}) => binding.unbind());
      saved.forEach(([object, position, quaternion, scale]) => { object.position.copy(position); object.quaternion.copy(quaternion); object.scale.copy(scale); });
      this.model.updateMatrixWorld(true);
    }
  }
}
