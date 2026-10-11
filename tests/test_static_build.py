import gzip
import json

import pytest

from build_static import build_site


@pytest.fixture
def sources(tmp_path):
    web, models = tmp_path / 'web', tmp_path / 'models'
    web.mkdir()
    (web / 'chibi-viewer.html').write_text('<script src="/assets/main.js"></script>')
    (web / 'main.js').write_text('import "./worker.js";')
    (web / 'worker.js').write_text('export const ready = true;')
    folder = models / '1030-40'
    folder.mkdir(parents=True)
    (folder / 'manifest.json').write_text(json.dumps({
        'model': 'model.glb', 'name': 'Rice Shower', 'outfit': 'Vampire Makeover!',
        'faces': {'presets': {'happy': {}}}, 'animation_labels': {'run': 'Run'},
    }))
    (folder / 'model.glb').write_bytes(b'glTF' + bytes(20))
    (folder / 'physics.json').write_text('{}')
    (models / 'export-complete.txt').write_text('Internal export details')
    (tmp_path / 'Config.json').write_text('{"secret": "not for publication"}')
    return web, models


def test_static_build_preserves_catalog_and_publishes_only_runtime_files(tmp_path, sources):
    web, models = sources
    output = tmp_path / 'site'
    build_site(output, models, web)
    entry = json.loads((output / 'api/chibi-models').read_text(encoding='utf-8'))['models'][0]
    assert entry['display_name'] == 'Rice Shower — Vampire Makeover!'
    assert entry['animation_labels'] == {'run': 'Run'}
    assert entry['faces']['presets'] == {'happy': {}}
    assert (output / entry['model_url'].lstrip('/')).read_bytes() == b'glTF' + bytes(20)
    compressed = output / (entry['model_url'].lstrip('/') + '.gz')
    assert gzip.decompress(compressed.read_bytes()) == b'glTF' + bytes(20)
    assert (output / 'index.html').read_bytes() == (output / 'chibi/index.html').read_bytes()
    main_url = (output / 'index.html').read_text().split('src="')[1].split('"')[0]
    main_path = output / main_url.lstrip('/')
    assert main_path.is_file() and main_path.with_name('worker.js').is_file()
    assert {path.name for path in output.rglob('*') if path.is_file()} == {
        'index.html', 'chibi-models', 'main.js', 'worker.js', entry['model_url'].split('/')[-1],
        compressed.name,
    }


def test_changed_models_and_scripts_get_new_cache_urls(tmp_path, sources):
    web, models = sources
    first, second = tmp_path / 'first', tmp_path / 'second'
    old = build_site(first, models, web)[0]
    (models / '1030-40/model.glb').write_bytes(b'glTF' + bytes(40))
    (web / 'worker.js').write_text('export const ready = false;')
    new = build_site(second, models, web)[0]
    assert old['model_url'] != new['model_url']
    assert (first / 'index.html').read_bytes() != (second / 'index.html').read_bytes()
    assert (first / old['model_url'].lstrip('/')).stat().st_size == 24
    assert (second / new['model_url'].lstrip('/')).stat().st_size == 44


def test_missing_lfs_data_stops_the_build(tmp_path, sources):
    web, models = sources
    (models / '1030-40/model.glb').write_text('version https://git-lfs.github.com/spec/v1')
    output = tmp_path / 'site'
    with pytest.raises(ValueError, match='Git LFS'):
        build_site(output, models, web)
    assert not output.exists()


def test_existing_output_is_never_overwritten(tmp_path, sources):
    web, models = sources
    output = tmp_path / 'site'
    output.mkdir()
    existing = output / 'keep.txt'
    existing.write_text('Existing deployment')
    with pytest.raises(FileExistsError):
        build_site(output, models, web)
    assert existing.read_text() == 'Existing deployment'
