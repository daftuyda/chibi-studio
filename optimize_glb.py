"""Compact exported GLBs without changing geometry, textures or animation samples.

Only dense, self-contained exports using KHR_materials_unlit are rewritten.
Other glTF layouts pass through unchanged, including third-party extensions.
"""
import json
import struct


def _key(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def _accessor_references(data):
    for mesh in data.get('meshes', []):
        for primitive in mesh['primitives']:
            if 'indices' in primitive:
                yield primitive, 'indices'
            for attributes in [primitive.get('attributes', {}), *primitive.get('targets', [])]:
                for name in attributes:
                    yield attributes, name
    for skin in data.get('skins', []):
        if 'inverseBindMatrices' in skin:
            yield skin, 'inverseBindMatrices'
    for animation in data.get('animations', []):
        for sampler in animation['samplers']:
            yield sampler, 'input'
            yield sampler, 'output'


def optimize_glb(source, animation_names=None):
    if len(source) < 28 or struct.unpack_from('<III', source) != (0x46546C67, 2, len(source)):
        return source
    length, kind = struct.unpack_from('<II', source, 12)
    if kind != 0x4E4F534A or 28 + length > len(source):
        return source
    data = json.loads(source[20:20 + length])
    binary_length, kind = struct.unpack_from('<II', source, 20 + length)
    if kind != 0x004E4942 or 28 + length + binary_length != len(source):
        return source
    buffers = data.get('buffers', [])
    accessors, views = data.get('accessors', []), data.get('bufferViews', [])
    if (len(buffers) != 1 or 'uri' in buffers[0]
            or set(data.get('extensionsUsed', [])) - {'KHR_materials_unlit'}
            or any('sparse' in a or 'bufferView' not in a or 'extensions' in a for a in accessors)
            or any(v.get('buffer', 0) != 0 or 'byteStride' in v or 'extensions' in v for v in views)):
        return source
    binary = source[28 + length:]
    if animation_names is not None:
        data['animations'] = [clip for clip in data.get('animations', []) if clip.get('name') in animation_names]
        if not data['animations']:
            raise ValueError('The requested mascot animation is missing.')

    def values(index):
        accessor = accessors[index]
        view = views[accessor['bufferView']]
        start = view.get('byteOffset', 0) + accessor.get('byteOffset', 0)
        components = {'SCALAR': 1, 'VEC3': 3, 'VEC4': 4}.get(accessor['type'])
        if accessor['componentType'] != 5126 or not components:
            return None
        return binary[start:start + accessor['count'] * components * 4]

    # Remove a transform track only when EVERY clip leaves that node/path at
    # its rest value. Keep rest tracks on paths that move in any other clip,
    # so transitions and the restoration of earlier poses stay identical.
    stationary = {}
    defaults = {'translation': [0, 0, 0], 'rotation': [0, 0, 0, 1], 'scale': [1, 1, 1]}
    animations = data.get('animations', [])
    for animation in animations:
        for channel in animation['channels']:
            target = channel['target']
            node, path = target.get('node'), target.get('path')
            if node is None or path not in defaults:
                continue
            key = node, path
            if 'matrix' in data['nodes'][node]:
                stationary[key] = False
                continue
            if stationary.get(key) is False:
                continue
            sampler = animation['samplers'][channel['sampler']]
            accessor = accessors[sampler['output']]
            rest = data['nodes'][node].get(path, defaults[path])
            expected = struct.pack('<' + 'f' * len(rest), *rest)
            stationary[key] = (sampler.get('interpolation', 'LINEAR') == 'LINEAR'
                               and not accessor.get('normalized')
                               and values(sampler['output']) == expected * accessor['count'])

    ends = {}
    def end_time(animation, channel):
        index = animation['samplers'][channel['sampler']]['input']
        if index not in ends:
            raw = values(index)
            ends[index] = struct.unpack_from('<f', raw, len(raw) - 4)[0]
        return ends[index]

    for animation in animations:
        original = animation['channels']
        if not original:
            continue
        channels = [channel for channel in original if not stationary.get(
            (channel['target'].get('node'), channel['target'].get('path')), False)]
        longest = max(original, key=lambda channel: end_time(animation, channel))
        # Animation duration is inferred from its tracks; keep its end even for
        # an entirely stationary clip or one whose motion ends before the clip.
        if not channels or max(end_time(animation, channel) for channel in channels) < end_time(animation, longest):
            channels.append(longest)
        samplers, mapping = [], {}
        for channel in channels:
            old = channel['sampler']
            if old not in mapping:
                mapping[old] = len(samplers)
                samplers.append(animation['samplers'][old])
            channel['sampler'] = mapping[old]
        animation['channels'], animation['samplers'] = channels, samplers

    references = list(_accessor_references(data))
    used_accessors = sorted({owner[key] for owner, key in references})
    used_views = sorted({accessors[index]['bufferView'] for index in used_accessors}
                        | {image['bufferView'] for image in data.get('images', []) if 'bufferView' in image})
    packed, new_views, view_map, seen_views = bytearray(), [], {}, {}
    for index in used_views:
        view = views[index]
        offset = view.get('byteOffset', 0)
        raw = binary[offset:offset + view['byteLength']]
        metadata = {key: value for key, value in view.items() if key not in ('buffer', 'byteOffset')}
        key = _key(metadata), raw
        if key not in seen_views:
            packed.extend(b'\0' * (-len(packed) % 4))
            seen_views[key] = len(new_views)
            new_views.append({**metadata, 'buffer': 0, 'byteOffset': len(packed)})
            packed.extend(raw)
        view_map[index] = seen_views[key]
    new_accessors, accessor_map, seen_accessors = [], {}, {}
    for index in used_accessors:
        accessor = {**accessors[index], 'bufferView': view_map[accessors[index]['bufferView']]}
        key = _key(accessor)
        if key not in seen_accessors:
            seen_accessors[key] = len(new_accessors)
            new_accessors.append(accessor)
        accessor_map[index] = seen_accessors[key]
    for owner, key in references:
        owner[key] = accessor_map[owner[key]]
    for image in data.get('images', []):
        if 'bufferView' in image:
            image['bufferView'] = view_map[image['bufferView']]
    for animation in animations:
        samplers, mapping, seen = [], {}, {}
        for index, sampler in enumerate(animation['samplers']):
            key = _key(sampler)
            if key not in seen:
                seen[key] = len(samplers)
                samplers.append(sampler)
            mapping[index] = seen[key]
        for channel in animation['channels']:
            channel['sampler'] = mapping[channel['sampler']]
        animation['samplers'] = samplers
    data['accessors'], data['bufferViews'] = new_accessors, new_views
    data['buffers'] = [{**buffers[0], 'byteLength': len(packed)}]
    metadata = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    metadata += b' ' * (-len(metadata) % 4)
    packed.extend(b'\0' * (-len(packed) % 4))
    result = (struct.pack('<IIIII', 0x46546C67, 2, 28 + len(metadata) + len(packed), len(metadata), 0x4E4F534A)
              + metadata + struct.pack('<II', len(packed), 0x004E4942) + packed)
    return result if animation_names is not None or len(result) < len(source) else source
