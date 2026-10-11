"""Plan Global or JP chibi imports from an installed master and local asset index."""
import argparse
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path

PROFILE = 'global-racewear-2'
COMMON_MOTIONS = [
    ('walk01', 'Walk', 'Movement'), ('run00', 'Run', 'Movement'), ('skip01', 'Skip', 'Movement'),
    ('hello04', 'Wave hello', 'Greetings'), ('bow02', 'Bow', 'Greetings'),
    ('bow03', 'Deep bow', 'Greetings'), ('clap01', 'Clap', 'Greetings'), ('come03', 'Come here', 'Greetings'),
    ('joy05', 'Celebrate', 'Reactions'), ('happy03', 'Happy', 'Reactions'), ('happy05', 'Delighted', 'Reactions'),
    ('yell01', 'Cheer 1', 'Reactions'), ('yell02', 'Cheer 2', 'Reactions'), ('yell03', 'Cheer 3', 'Reactions'),
    ('gatts04', 'Determined 1', 'Reactions'), ('gatts06', 'Determined 2', 'Reactions'),
    ('shy02', 'Shy 1', 'Reactions'), ('shy03', 'Shy 2', 'Reactions'), ('shy06', 'Shy 3', 'Reactions'),
    ('hope01', 'Hopeful', 'Reactions'), ('idea01', 'An idea', 'Reactions'), ('hungry01', 'Hungry', 'Reactions'),
    ('udekumi02', 'Arms crossed', 'Poses'), ('koshiate01', 'Hands on hips', 'Poses'),
    ('muneate02', 'Hand on heart', 'Poses'), ('tekumi01', 'Hands together', 'Poses'),
    ('pose03', 'Strike a pose', 'Poses'), ('soppo06', 'Look away', 'Poses'),
    ('dance01', 'Dance 1', 'Dance'), ('dance05', 'Dance 2', 'Dance'), ('dance09', 'Dance 3', 'Dance'),
    ('dance11', 'Dance 4', 'Dance'), ('dance13', 'Dance 5', 'Dance'), ('dance14', 'Dance 6', 'Dance'),
    ('dance15', 'Dance 7', 'Dance'),
]


def racewear(master, now):
    with sqlite3.connect(master.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute('''
            SELECT d.id dress_id, d.chara_id character_id, d.body_type_sub, d.have_mini,
                   c.skin, c.tail_model_id, n.text name, COALESCE(ct.text, t.text) outfit, cr.card_id
            FROM dress_data d JOIN chara_data c ON c.id = d.chara_id
            LEFT JOIN text_data n ON n.category = 6 AND n."index" = d.chara_id
            LEFT JOIN text_data t ON t.category = 14 AND t."index" = d.id
            LEFT JOIN (SELECT race_dress_id, MIN(card_id) card_id FROM card_rarity_data
                       WHERE rarity >= 3 GROUP BY race_dress_id) cr ON cr.race_dress_id = d.id
            LEFT JOIN text_data ct ON ct.category = 5 AND ct."index" = cr.card_id
            WHERE d.use_race = 1 AND d.chara_id BETWEEN 1000 AND 2999
              AND d.start_time <= ? AND (d.end_time = 0 OR d.end_time >= ?)
              AND c.start_date <= ?
            ORDER BY d.chara_id, d.body_type_sub, d.id
        ''', (now, now, now))]


def plan_import(rows, assets, model_root, region='global', translations=None, global_names=None):
    if region not in ('global', 'jp'):
        raise ValueError('Choose the global or jp library.')
    index = {asset['name']: asset for asset in assets}
    items, unavailable, seen = [], [], set()
    translations, global_names = translations or {}, global_names or {}
    global_character_names = {key[0]: value['name'] for key, value in global_names.items() if value.get('name')}

    def translated(category, ident, fallback):
        value = translations.get(str(category), {}).get(str(ident))
        return ' '.join(value.split()) if isinstance(value, str) and value.strip() else fallback

    def title_text(value):
        value = ' '.join(value.split())
        return value[1:-1] if value.startswith('[') and value.endswith(']') else value

    def complete(path):
        entry = index.get(path)
        return entry and entry['present'] and not entry.get('missing_dependencies')

    for row in rows:
        if region == 'jp' and not row['have_mini']:
            continue
        chara = row['character_id']
        costume = f"{row['body_type_sub']:02d}"
        # Multiple database entries can refer to the same physical chibi costume.
        if (chara, costume) in seen:
            continue
        seen.add((chara, costume))
        model_id = str(chara) if costume == '00' else f'{chara}-{costume}'
        original_name = row['name'] or f'Character {chara}'
        original_title = title_text(row['outfit'] or f'Racing outfit {costume}')
        name, title = original_name, original_title
        if region == 'jp':
            known = global_names.get((chara, costume), {})
            name = global_character_names.get(chara) or translated(6, chara, original_name)
            # A generic translated dress label must not replace an untranslated card title.
            translated_title = translated(5, row['card_id'], original_title) if row.get('card_id') else translated(14, row['dress_id'], original_title)
            title = known.get('outfit') or title_text(translated_title)
            model_id = 'jp-' + model_id
        item = {'id': model_id, 'character_id': chara, 'dress_id': row['dress_id'], 'costume': costume,
                'region': region, 'name': name, 'outfit': title,
                'output': str((model_root / model_id).resolve())}
        if region == 'jp':
            item.update(name_jp=original_name, outfit_jp=original_title)
        item['available_in'] = ['global', 'jp'] if region == 'jp' and (chara, costume) in global_names else [region]
        head = f'3d/chara/mini/head/mchr{chara}_{costume}'
        if f'{head}/pfb_mchr{chara}_{costume}_hair' not in index:
            head = f'3d/chara/mini/head/mchr{chara}_00'
        head_name = head.rsplit('/', 1)[-1]
        required = [f'3d/chara/mini/body/mbdy{chara}_{costume}/pfb_mbdy{chara}_{costume}',
                    f'{head}/pfb_{head_name}_hair', '3d/chara/mini/head/mchr0001_00/pfb_mchr0001_00_face0']
        prefixes = [head + '/textures/', f"3d/chara/mini/head/mchr0001_00/textures/tex_mchr0001_00_face0_{row['skin']}"]
        if row['tail_model_id'] > 0:
            tail = f"mtail{row['tail_model_id']:04d}_00"
            required.append(f'3d/chara/mini/tail/{tail}/pfb_{tail}')
            prefixes.append(f'3d/chara/mini/tail/{tail}/textures/tex_{tail}_{chara:04d}')
        required += [name for name in index if any(name.startswith(prefix) for prefix in prefixes)]
        physics = [f'3d/chara/mini/body/mbdy{chara}_{costume}/clothes/pfb_mbdy{chara}_{costume}_cloth00',
                   f'{head}/clothes/pfb_{head_name}_cloth00']
        if row['tail_model_id'] > 0:
            physics.append(f'3d/chara/mini/tail/{tail}/clothes/pfb_{tail}_cloth00')
        item['physics_assets'] = [path for path in physics if complete(path)]
        missing = [name for name in required if not complete(name)]
        if missing:
            unavailable.append({**item, 'reason': f'Chibi assets are missing from the local {region} cache', 'missing': missing})
            continue

        motions, labels, groups = [], {}, {}

        def add(path, label, group):
            if path not in motions and complete(path):
                motions.append(path)
                clip = path.rsplit('/', 1)[-1]
                labels[clip], groups[clip] = label, group

        character_prefix = f'3d/motion/mini/event/body/chara/chr{chara}_'
        add(f'{character_prefix}00/anm_min_eve_chr{chara}_00_idle01_loop', 'Idle', 'Character')
        for suffix, label, group in COMMON_MOTIONS:
            add(f'3d/motion/mini/event/body/type00/anm_min_eve_type00_{suffix}_loop', label, group)
        if region == 'jp':
            # Standalone body loops do not include the game's scene props or cameras.
            names = {'akire': 'Exasperated', 'bit': 'Nervous', 'book': 'Read', 'bookshelf': 'Browse books',
                     'byebye': 'Wave goodbye', 'chair': 'Sit', 'chuni': 'Dramatic pose', 'drinkcupa': 'Drink',
                     'fight': 'Fighting spirit', 'gatts': 'Determined', 'good': 'Thumbs up',
                     'homestand': 'Standing pose', 'hope': 'Hopeful', 'hungry': 'Hungry', 'idea': 'An idea',
                     'ikaku': 'Intimidate', 'joy': 'Celebrate', 'kuchiate': 'Hand to mouth', 'laugh': 'Laugh',
                     'muneate': 'Hand on heart', 'music': 'Music', 'near': 'Lean closer', 'oh': 'Oh!',
                     'peace': 'Peace sign', 'pose': 'Pose', 'present': 'Give a present', 'request': 'Please!',
                     'run': 'Run', 'see': 'Look around', 'showtime': 'Showtime', 'shy': 'Shy',
                     'soppo': 'Look away', 'start': 'Ready to go', 'sudachi': 'Standing pose',
                     'surprise': 'Surprised', 'tired': 'Tired', 'topin': 'Jump in', 'udekumi': 'Arms crossed', 'smt': 'Story pose',
                     'walk': 'Walk'}
            for path in sorted(index):
                match = re.fullmatch(r'3d/motion/mini/event/body/type00/anm_min_eve_type00_(.+)_loop', path)
                if not match:
                    continue
                suffix = match[1]
                stem = re.match(r'[a-z]+', suffix)[0]
                label = names.get(stem, stem.capitalize()) + ' ' + suffix[len(stem):].replace('_', ' ')
                group = 'Movement' if stem in {'run', 'walk', 'topin'} else 'Activities' if stem in {
                    'book', 'bookshelf', 'chair', 'drinkcupa', 'music', 'present'} else 'Reactions'
                add(path, label.strip(), group)
        # Original character-specific looping poses, for this outfit or the base outfit.
        for path in sorted(index):
            if path.startswith(character_prefix) and path.endswith('_loop') and any(
                    f'/chr{chara}_{variant}/' in path for variant in {'00', costume}):
                suffix = path.rsplit('/', 1)[-1].split(f'chr{chara}_', 1)[-1]
                add(path, 'Character pose ' + suffix.replace('_loop', '').replace('_', ' '), 'Character')
        if not motions:
            unavailable.append({**item, 'reason': 'No compatible local mini animations', 'missing': []})
            continue
        signature = {'profile': PROFILE if region == 'global' else 'jp-racewear-1', 'models': [(name, index[name]['revision']) for name in required],
                     'motions': [(name, index[name]['revision']) for name in motions]}
        item.update(motions=motions, animation_labels=labels, animation_groups=groups,
                    import_profile=hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest())
        items.append(item)
    return items, unavailable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--master', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--region', choices=('global', 'jp'), default='global')
    parser.add_argument('--translations', type=Path, help='Optional UmaTL text_data_dict.json for English JP names')
    parser.add_argument('--global-master', type=Path, help='Optional Global master.mdb to refresh availability and official names')
    parser.add_argument('--global-roster', type=Path, default=Path(__file__).with_name('global-outfits.json'))
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    assets = json.loads(args.inventory.read_text(encoding='utf-8'))['assets']
    rows = racewear(args.master, int(time.time()))
    translations = json.loads(args.translations.read_text(encoding='utf-8')) if args.translations else {}
    global_names = {}
    if args.region == 'jp':
        if args.global_master:
            for row in racewear(args.global_master, int(time.time())):
                title = ' '.join((row['outfit'] or '').split()).strip('[]')
                global_names.setdefault((row['character_id'], f"{row['body_type_sub']:02d}"),
                                        {'name': row['name'], 'outfit': title})
        else:
            roster = json.loads(args.global_roster.read_text(encoding='utf-8'))['outfits']
            global_names = {(item['character_id'], item['costume']): item for item in roster.values()}
    items, unavailable = plan_import(rows, assets, args.models, args.region, translations, global_names)
    request = {'mode': 'batch', 'output': str(args.output.parent.resolve()), 'items': items,
               'unavailable': unavailable, 'force': args.force, 'source': f'Installed {args.region} master and asset cache'}
    args.output.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding='utf-8')
    count = len({item['character_id'] for item in items})
    print(f"Ready to import {len(items)} racing outfits for {count} characters; {len(unavailable)} unavailable locally.")
    print(f"Animation library: {min(len(item['motions']) for item in items) if items else 0} to {max(len(item['motions']) for item in items) if items else 0} clips per outfit.")


if __name__ == '__main__':
    main()
