"""Global racewear selection, canonical alt titles, and lossless metadata updates."""
import json
import sqlite3
import struct

from tools.chibi_export.catalog import plan_import, racewear
from tools.chibi_export.refresh_metadata import refresh, update_glb


def test_global_catalog_uses_card_title_and_release_dates(tmp_path):
    master = tmp_path / 'master.mdb'
    with sqlite3.connect(master) as db:
        db.executescript('''
            CREATE TABLE dress_data(id, chara_id, body_type_sub, have_mini, use_race, start_time, end_time);
            CREATE TABLE chara_data(id, skin, tail_model_id, start_date);
            CREATE TABLE text_data(category, "index", text);
            CREATE TABLE card_rarity_data(card_id, race_dress_id, rarity);
            INSERT INTO chara_data VALUES(1056, 0, 1, 10);
            INSERT INTO dress_data VALUES(105650, 1056, 50, 1, 1, 10, 1000),
                (105699, 1056, 99, 1, 1, 900, 1000), (105651, 1056, 51, 1, 0, 10, 1000);
            INSERT INTO text_data VALUES(6, 1056, 'Matikanefukukitaru'),
                (14, 105650, 'Signature Racewear 2'), (5, 105602, '[Lucky Tidings]');
            INSERT INTO card_rarity_data VALUES(105602, 105650, 3), (105602, 105650, 4), (105602, 105650, 5);
        ''')
    before = master.read_bytes()
    rows = racewear(master, 100)
    assert len(rows) == 1
    assert rows[0]['outfit'] == '[Lucky Tidings]'
    assert rows[0]['body_type_sub'] == 50
    assert master.read_bytes() == before


def asset(name, **overrides):
    return {'name': name, 'present': True, 'revision': 'content-hash', 'missing_dependencies': [], **overrides}


def example_assets():
    return [asset(name) for name in [
        '3d/chara/mini/body/mbdy1030_40/pfb_mbdy1030_40',
        '3d/chara/mini/head/mchr1030_00/pfb_mchr1030_00_hair',
        '3d/chara/mini/head/mchr0001_00/pfb_mchr0001_00_face0',
        '3d/chara/mini/head/mchr1030_00/textures/tex_mchr1030_00_eye_diff',
        '3d/motion/mini/event/body/chara/chr1030_00/anm_min_eve_chr1030_00_idle01_loop',
        '3d/motion/mini/event/body/chara/chr1030_00/anm_min_eve_chr1030_40_res01_loop',
        '3d/motion/mini/event/body/chara/chr1001_00/anm_min_eve_chr1001_00_idle01_loop',
        '3d/motion/mini/event/body/type00/anm_min_eve_type00_walk01_loop',
    ]]


def row(**overrides):
    return {'character_id': 1030, 'dress_id': 103040, 'body_type_sub': 40, 'have_mini': 1,
            'skin': 0, 'tail_model_id': 0, 'name': 'Rice Shower', 'outfit': '[Vampire Makeover!]', **overrides}


def test_alt_costume_keeps_its_title_and_uses_local_base_hair(tmp_path):
    items, unavailable = plan_import([row(), row(dress_id=999999)], example_assets(), tmp_path)
    assert not unavailable
    assert len(items) == 1, 'Two dress rows referencing one chibi should not create duplicates.'
    item = items[0]
    assert item['id'] == '1030-40'
    assert item['outfit'] == 'Vampire Makeover!'
    assert len(item['motions']) == 3
    assert not any('chr1001' in motion for motion in item['motions'])
    assert item['animation_groups']['anm_min_eve_type00_walk01_loop'] == 'Movement'


def test_incomplete_dependencies_are_reported_without_partial_import(tmp_path):
    assets = example_assets()
    assets[0]['missing_dependencies'] = ['missing-body-texture']
    items, unavailable = plan_import([row()], assets, tmp_path)
    assert not items
    assert unavailable[0]['id'] == '1030-40'
    assert 'mbdy1030_40' in unavailable[0]['missing'][0]


def test_changed_motion_asset_invalidates_resume_profile(tmp_path):
    assets = example_assets()
    first, _ = plan_import([row()], assets, tmp_path)
    assets[-1]['revision'] = 'updated-motion'
    second, _ = plan_import([row()], assets, tmp_path)
    assert first[0]['import_profile'] != second[0]['import_profile']


def test_jp_library_preserves_japanese_names_and_prefers_available_english(tmp_path):
    source = row(name='ライスシャワー', outfit='[ライスの衣装]', card_id=103002)
    translations = {'6': {'1030': 'Rice Shower'}, '5': {'103002': '[Vampire Makeover!]'}}
    assets = example_assets() + [asset('3d/motion/mini/event/body/type00/anm_min_eve_type00_laugh21_loop')]
    items, unavailable = plan_import([source], assets, tmp_path, 'jp', translations)
    assert not unavailable
    item = items[0]
    assert item['id'] == 'jp-1030-40' and item['region'] == 'jp'
    assert item['available_in'] == ['jp']
    assert item['name'] == 'Rice Shower' and item['outfit'] == 'Vampire Makeover!'
    assert item['name_jp'] == 'ライスシャワー' and item['outfit_jp'] == 'ライスの衣装'
    assert item['output'] == str(tmp_path / 'jp-1030-40')
    assert item['animation_labels']['anm_min_eve_type00_laugh21_loop'] == 'Laugh 21'
    assert not any('chr1001' in motion for motion in item['motions'])
    global_items, _ = plan_import([source], assets, tmp_path)
    assert global_items[0]['id'] == '1030-40'
    assert len(item['motions']) == len(global_items[0]['motions']) + 1


def test_jp_translation_fallback_and_official_global_title(tmp_path):
    source = row(name='ライスシャワー', outfit='[日本語の衣装]', card_id=103002)
    items, _ = plan_import([source], example_assets(), tmp_path, 'jp')
    assert items[0]['name'] == 'ライスシャワー' and items[0]['outfit'] == '日本語の衣装'
    official = {(1030, '40'): {'name': 'Rice Shower', 'outfit': 'Vampire Makeover!'}}
    items, _ = plan_import([source], example_assets(), tmp_path, 'jp',
                           {'5': {'103002': '[Fan title]'}}, official)
    assert items[0]['outfit'] == 'Vampire Makeover!'
    assert items[0]['available_in'] == ['global', 'jp']
    assert items[0]['outfit_jp'] == '日本語の衣装'
    items, _ = plan_import([source], example_assets(), tmp_path, 'jp',
                           {'14': {'103040': 'Signature Racewear'}})
    assert items[0]['outfit'] == '日本語の衣装', 'Preserve the actual alt title instead of a generic dress label.'
    items, missing = plan_import([row(have_mini=0)], example_assets(), tmp_path, 'jp')
    assert not items and not missing


def glb():
    metadata = json.dumps({'asset': {'version': '2.0'}, 'extras': {'retained': 'yes'}}).encode()
    metadata += b' ' * (-len(metadata) % 4)
    binary = struct.pack('<II', 8, 0x004E4942) + b'original'
    return struct.pack('<IIIII', 0x46546C67, 2, 20 + len(metadata) + len(binary), len(metadata), 0x4E4F534A) + metadata + binary


def test_face_refresh_preserves_geometry_animation_and_other_extras():
    source = glb()
    output = update_glb(source, {'presets': {'excited': {'eyes': 13}}}, {'display_name': 'Uma — Special ☆ Outfit'})
    old_length, = struct.unpack_from('<I', source, 12)
    new_length, = struct.unpack_from('<I', output, 12)
    assert source[20 + old_length:] == output[20 + new_length:]
    assert struct.unpack_from('<I', output, 8)[0] == len(output)
    assert new_length % 4 == 0
    extras = json.loads(output[20:20 + new_length])['extras']
    assert extras['retained'] == 'yes'
    assert extras['umaCharacter']['display_name'] == 'Uma — Special ☆ Outfit'


def test_metadata_upgrade_is_repeatable_and_updates_canonical_title(tmp_path):
    folder = tmp_path / '1056-50'
    folder.mkdir()
    (folder / 'model.glb').write_bytes(glb())
    manifest = {'name': 'Matikanefukukitaru', 'outfit': 'Signature Racewear 2', 'model': 'model.glb',
                'faces': {'meshes': {'M_Eye': {'part': 'eyes'}}, 'presets': {}}}
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    presets = {'blink': 8, 'presets': {'happy': {'eyes': 9}}}
    catalog = {'items': [{'id': '1056-50', 'name': 'Matikanefukukitaru', 'outfit': 'Lucky Tidings', 'animation_labels': {}, 'animation_groups': {}}]}
    assert refresh(tmp_path, presets, catalog) == 1
    final = (folder / 'model.glb').read_bytes()
    assert refresh(tmp_path, presets, catalog) == 0
    assert (folder / 'model.glb').read_bytes() == final
    assert json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))['display_name'] == 'Matikanefukukitaru — Lucky Tidings'


def test_physics_metadata_upgrade_retains_binary_and_detects_new_cloth(tmp_path):
    folder = tmp_path / '1032'; folder.mkdir()
    source = glb(); (folder / 'model.glb').write_bytes(source)
    (folder / 'manifest.json').write_text(json.dumps({'name': 'Agnes Tachyon', 'outfit': 'tach-nology',
        'model': 'model.glb', 'faces': {'meshes': {}, 'presets': {}}}), encoding='utf-8')
    physics = {'version': 1, 'sources': [{'data': {'springParam': [{'_boneName': 'Sp_El_Sleeve0_L_00'}]}}]}
    (folder / 'physics.json').write_text(json.dumps(physics), encoding='utf-8')
    assert refresh(tmp_path, {'presets': {}}) == 1
    result = (folder / 'model.glb').read_bytes()
    old_length, = struct.unpack_from('<I', source, 12)
    new_length, = struct.unpack_from('<I', result, 12)
    assert result[20 + new_length:] == source[20 + old_length:]
    assert json.loads(result[20:20 + new_length])['extras']['umaPhysics'] == physics
    assert refresh(tmp_path, {'presets': {}}) == 0
    physics['sources'][0]['data']['springParam'].append({'_boneName': 'Sp_El_Sleeve0_R_00'})
    (folder / 'physics.json').write_text(json.dumps(physics), encoding='utf-8')
    assert refresh(tmp_path, {'presets': {}}) == 1
