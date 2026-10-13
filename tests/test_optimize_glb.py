import json
import struct

from optimize_glb import optimize_glb


def unpack(source):
    length = struct.unpack_from('<I', source, 12)[0]
    return json.loads(source[20:20 + length]), source[28 + length:]


def pack(data, binary):
    data['buffers'] = [{'byteLength': len(binary)}]
    metadata = json.dumps(data).encode()
    metadata += b' ' * (-len(metadata) % 4)
    binary += b'\0' * (-len(binary) % 4)
    return (struct.pack('<IIIII', 0x46546C67, 2, 28 + len(metadata) + len(binary), len(metadata), 0x4E4F534A)
            + metadata + struct.pack('<II', len(binary), 0x004E4942) + binary)


def fixture():
    data = {'asset': {'version': '2.0'}, 'nodes': [{'name': 'root'}, {'name': 'still'}],
            'scenes': [{'nodes': [0, 1]}], 'scene': 0, 'accessors': [], 'bufferViews': [],
            'extras': {'umaFaces': {'presets': {'happy': {}}}, 'umaPhysics': {'sources': []}}}
    binary = bytearray()
    def accessor(values, shape):
        raw = struct.pack('<' + 'f' * len(values), *values)
        view = len(data['bufferViews'])
        data['bufferViews'].append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(raw)})
        binary.extend(raw)
        index = len(data['accessors'])
        data['accessors'].append({'bufferView': view, 'componentType': 5126,
                                  'count': len(values) // (3 if shape == 'VEC3' else 1), 'type': shape})
        return index
    animations = []
    for name, positions in [('move', [0, 0, 0, 1, 2, 3]), ('rest', [0, 0, 0, 0, 0, 0])]:
        samplers, channels = [], []
        for node, path, values in [(0, 'translation', positions), (0, 'scale', [1] * 6),
                                    (1, 'translation', [0] * 6), (1, 'scale', [1] * 6)]:
            index = len(samplers)
            samplers.append({'input': accessor([0, 2], 'SCALAR'), 'output': accessor(values, 'VEC3')})
            channels.append({'sampler': index, 'target': {'node': node, 'path': path}})
        animations.append({'name': name, 'channels': channels, 'samplers': samplers})
    data['animations'] = animations
    return data, bytes(binary)


def track_values(data, binary, animation):
    result = {}
    for channel in animation['channels']:
        sampler = animation['samplers'][channel['sampler']]
        values = []
        for key in ('input', 'output'):
            accessor = data['accessors'][sampler[key]]
            view = data['bufferViews'][accessor['bufferView']]
            start = view.get('byteOffset', 0) + accessor.get('byteOffset', 0)
            count = accessor['count'] * (3 if accessor['type'] == 'VEC3' else 1)
            values.append(binary[start:start + count * 4])
        result[channel['target']['node'], channel['target']['path']] = values
    return result


def test_compaction_preserves_moving_and_restoring_tracks_exactly():
    data, binary = fixture()
    source = pack(data, binary)
    compact = optimize_glb(source)
    output, packed = unpack(compact)
    assert len(compact) < len(source)
    assert output['extras'] == data['extras']
    assert output['nodes'] == data['nodes']
    assert len(output['accessors']) < len(data['accessors'])
    assert [clip['name'] for clip in output['animations']] == ['move', 'rest']
    for old, new in zip(data['animations'], output['animations']):
        before, after = track_values(data, binary, old), track_values(output, packed, new)
        assert set(after) == {(0, 'translation')}
        assert after[0, 'translation'] == before[0, 'translation']
    # A second pass must not change the already compact file.
    assert optimize_glb(compact) == compact


def test_static_tracks_preserve_clip_duration_and_mascot_keeps_only_run():
    data, binary = fixture()
    data['animations'] = [data['animations'][1]]
    data['animations'][0]['name'] = 'run'
    compact, packed = unpack(optimize_glb(pack(data, binary), {'run'}))
    assert len(compact['animations']) == 1
    tracks = track_values(compact, packed, compact['animations'][0])
    assert len(tracks) == 1
    assert struct.unpack('<ff', next(iter(tracks.values()))[0]) == (0, 2)


def test_matrix_nodes_do_not_lose_transform_overrides():
    data, binary = fixture()
    data['nodes'][1]['matrix'] = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 5, 0, 0, 1]
    compact, packed = unpack(optimize_glb(pack(data, binary)))
    for clip in compact['animations']:
        tracks = track_values(compact, packed, clip)
        assert (1, 'translation') in tracks
        assert (1, 'scale') in tracks


def test_unknown_extensions_are_left_untouched():
    data, binary = fixture()
    data['extensionsUsed'] = ['EXT_meshopt_compression']
    source = pack(data, binary)
    assert optimize_glb(source) == source
