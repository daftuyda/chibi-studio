"""Refresh portable face presets and outfit names without resampling existing models."""
import argparse
import hashlib
import json
import struct
from pathlib import Path


def update_glb(payload, faces, character, animations=None, physics=None):
    if len(payload) < 20:
        raise ValueError('Incomplete GLB')
    magic, version, length, json_length, chunk_type = struct.unpack_from('<IIIII', payload)
    if (magic, version, length, chunk_type) != (0x46546C67, 2, len(payload), 0x4E4F534A) or json_length > len(payload) - 20:
        raise ValueError('Invalid glTF 2 GLB')
    document = json.loads(payload[20:20 + json_length])
    for node in document.get('nodes', []):
        if 'skin' in node:
            for property_name in ('translation', 'rotation', 'scale'):
                node.pop(property_name, None)
    extras = document.setdefault('extras', {})
    extras['umaFaces'] = faces
    extras['umaCharacter'] = character
    if animations is not None:
        extras['umaAnimations'] = animations
    if physics is not None:
        extras['umaPhysics'] = physics
    metadata = json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    metadata += b' ' * (-len(metadata) % 4)
    # Keep the BIN chunk (meshes, textures, skinning and animations) byte for byte.
    remaining = payload[20 + json_length:]
    return struct.pack('<IIIII', magic, version, 20 + len(metadata) + len(remaining), len(metadata), chunk_type) + metadata + remaining


def refresh(root, presets, catalog=None):
    changed = 0
    entries = {item['id']: item for item in (catalog or {}).get('items', [])}
    for path in sorted(root.glob('*/manifest.json')):
        manifest = json.loads(path.read_text(encoding='utf-8'))
        previous = dict(manifest)
        if manifest.get('model') != 'model.glb' or not isinstance(manifest.get('faces', {}).get('meshes'), dict):
            continue
        faces = {**manifest['faces'], **presets}
        if path.parent.name in entries:
            item = entries[path.parent.name]
            for key in ('name', 'outfit', 'animation_labels', 'animation_groups'):
                manifest[key] = item[key]
        character = {key: manifest.get(key) for key in ('name', 'outfit', 'character_id', 'costume', 'dress_id')}
        character['display_name'] = f"{character['name']} — {character['outfit']}"
        physics_path = path.with_name('physics.json')
        physics = None
        if physics_path.is_file():
            physics_bytes = physics_path.read_bytes()
            physics = json.loads(physics_bytes)
            manifest['physics_version'] = hashlib.sha256(physics_bytes).hexdigest()
        if faces == previous['faces'] and previous == manifest and manifest.get('display_name') == character['display_name'] and manifest.get('metadata_version') == 2:
            continue
        model = path.parent / 'model.glb'
        updated = update_glb(model.read_bytes(), faces, character, {'labels': manifest.get('animation_labels', {}), 'groups': manifest.get('animation_groups', {})}, physics)
        temp = model.with_suffix('.glb.tmp')
        temp.write_bytes(updated)
        temp.replace(model)
        manifest.update(faces=faces, display_name=character['display_name'], metadata_version=2)
        temp = path.with_suffix('.json.tmp')
        temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)
        changed += 1
    return changed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--catalog', type=Path)
    args = parser.parse_args()
    presets = json.loads(Path(__file__).with_name('face-presets.json').read_text(encoding='utf-8'))
    catalog = json.loads(args.catalog.read_text(encoding='utf-8')) if args.catalog else None
    count = refresh(args.models, presets, catalog)
    print(f'Updated display names and {len(presets["presets"])} expression presets in {count} local outfits.')
