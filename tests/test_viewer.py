import json
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import viewer
from viewer import make_server, read_model


@contextmanager
def running(tmp_path, use_defaults=False):
    models, web = tmp_path / 'models', tmp_path / 'web'
    models.mkdir(); web.mkdir()
    (web / 'chibi-viewer.html').write_text('<title>Chibi Studio</title>', encoding='utf-8')
    (web / 'test.js').write_text('export const value = 1;', encoding='utf-8')
    server = make_server(port=0, models=None if use_defaults else models, web=web)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', models
    finally:
        server.shutdown(); server.server_close(); thread.join()


def add_model(root, **changes):
    folder = root / '1030-40'; folder.mkdir(exist_ok=True)
    metadata = {'model': 'model.glb', 'name': 'Rice Shower', 'outfit': 'Vampire Makeover!',
                'character_id': 1030, 'costume': '40', 'animation_groups': {'run': 'Movement'}}
    metadata.update(changes)
    (folder / 'manifest.json').write_text(json.dumps(metadata), encoding='utf-8')
    (folder / 'model.glb').write_bytes(b'glTF' + bytes(20))
    return folder


def test_standalone_http_and_catalog(tmp_path):
    with running(tmp_path) as (url, models):
        assert json.load(urlopen(url + '/api/chibi-models')) == {'models': []}
        add_model(models)
        result = json.load(urlopen(url + '/api/chibi-models'))['models'][0]
        assert result['display_name'] == 'Rice Shower — Vampire Makeover!'
        assert result['animation_groups'] == {'run': 'Movement'}
        assert result['region'] == 'global'
        assert urlopen(url + result['model_url']).read().startswith(b'glTF')
        assert b'Chibi Studio' in urlopen(url).read()
        response = urlopen(Request(url + '/assets/test.js', method='HEAD'))
        assert response.headers['Content-Type'] == 'text/javascript'
        assert response.read() == b''


def test_shared_jp_model_is_available_in_both_filters_and_keeps_search_names(tmp_path):
    with running(tmp_path) as (url, models):
        add_model(models, region='jp', available_in=['global', 'jp'],
                  name_jp='ライスシャワー', outfit_jp='ヴァンパイア')
        entries = {entry['id']: entry for entry in json.load(urlopen(url + '/api/chibi-models'))['models']}
        assert len(entries) == 1
        jp = entries['1030-40']
        assert jp['available_in'] == ['global', 'jp']
        assert jp['region'] == 'jp' and jp['name_jp'] == 'ライスシャワー'
        assert jp['outfit_jp'] == 'ヴァンパイア'
        assert urlopen(url + jp['model_url']).read().startswith(b'glTF')
        add_model(models, region='jp')
        assert json.load(urlopen(url + '/api/chibi-models'))['models'][0]['available_in'] == ['jp']


def test_server_loads_included_models_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(viewer, 'ROOT', tmp_path)
    monkeypatch.delenv('CHIBI_MODELS_DIR', raising=False)
    with running(tmp_path, use_defaults=True) as (url, models):
        add_model(models)
        entries = json.load(urlopen(url + '/api/chibi-models'))['models']
        assert [entry['id'] for entry in entries] == ['1030-40']
        assert urlopen(url + entries[0]['model_url']).read().startswith(b'glTF')


@pytest.mark.parametrize('use_defaults', [True, False])
def test_explicit_library_takes_precedence_over_environment(tmp_path, monkeypatch, use_defaults):
    monkeypatch.setattr(viewer, 'ROOT', tmp_path)
    alternative = tmp_path / 'alternative'
    alternative.mkdir()
    add_model(alternative, name='Environment library')
    monkeypatch.setenv('CHIBI_MODELS_DIR', str(alternative))
    with running(tmp_path, use_defaults=use_defaults) as (url, models):
        add_model(models, name='Explicit library')
        entries = json.load(urlopen(url + '/api/chibi-models'))['models']
        assert len(entries) == 1
        assert entries[0]['name'] == ('Environment library' if use_defaults else 'Explicit library')


@pytest.mark.parametrize('route', ['/viewer.py', '/.local/', '/assets/../secret.txt',
                                    '/assets/%2e%2e/secret.txt', '/chibi-models/../secret.txt', '/assets/'])
def test_server_does_not_expose_other_files(tmp_path, route):
    (tmp_path / 'secret.txt').write_text('private', encoding='utf-8')
    with running(tmp_path) as (url, models):
        with pytest.raises(HTTPError) as error:
            urlopen(url + route)
        assert error.value.code == 404


@pytest.mark.parametrize('target', ['../outside.glb', '../../outside.glb', '/outside.glb', 'C:\\outside.glb'])
def test_manifest_cannot_escape_model_folder(tmp_path, target):
    add_model(tmp_path, model=target)
    assert read_model(tmp_path, '1030-40') is None


def test_invalid_manifest_and_model_are_ignored(tmp_path):
    folder = add_model(tmp_path)
    (folder / 'model.glb').write_bytes(b'invalid')
    assert read_model(tmp_path, '1030-40') is None
    (folder / 'manifest.json').write_text('{invalid', encoding='utf-8')
    assert read_model(tmp_path, '1030-40') is None
