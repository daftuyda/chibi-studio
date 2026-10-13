"""Build Chibi Studio for static hosting. Python 3.10+, no packages."""
import argparse
import gzip
import hashlib
import io
import json
import shutil
from pathlib import Path

from viewer import ROOT, model_directory, read_model
from optimize_glb import optimize_glb


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build_site(output, models=None, web=None):
    output = Path(output).resolve()
    models = Path(models if models is not None else model_directory()).resolve()
    web = Path(web if web is not None else ROOT / 'web').resolve()
    if output.exists():
        raise FileExistsError(f'Choose a new output directory; {output} already exists.')
    for source in (models, web):
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError('The output directory must be separate from the source files.')

    # Validate the complete library before creating a deployment. A clone with
    # missing LFS objects must fail here instead of publishing an empty studio.
    entries = []
    for folder in sorted(models.iterdir()):
        if not folder.is_dir():
            continue
        result = read_model(models, folder.name)
        if result is None:
            raise ValueError(f'Invalid or missing model in {folder.name}; check its manifest and Git LFS files.')
        entries.append(result)
    if not entries:
        raise ValueError('The character library is empty.')

    html = (web / 'chibi-viewer.html').read_text(encoding='utf-8')
    assets = []
    digest = hashlib.sha256()
    for path in sorted(web.rglob('*')):
        if not path.is_file() or path == web / 'chibi-viewer.html':
            continue
        if not path.resolve().is_relative_to(web):
            raise ValueError(f'Asset points outside the web directory: {path.name}')
        relative = path.relative_to(web)
        digest.update(relative.as_posix().encode('utf-8') + b'\0')
        digest.update(bytes.fromhex(file_hash(path)))
        assets.append((path, relative))
    asset_version = digest.hexdigest()[:20]

    output.mkdir(parents=True)
    for path, relative in assets:
        target = output / 'assets' / asset_version / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    html = html.replace('/assets/', f'/assets/{asset_version}/')
    (output / 'index.html').write_text(html, encoding='utf-8')
    (output / 'chibi').mkdir()
    (output / 'chibi' / 'index.html').write_text(html, encoding='utf-8')

    def publish_model(ident, name, content):
        version = hashlib.sha256(content).hexdigest()[:20]
        relative = Path('chibi-models') / ident / f'{name}.{version}.glb'
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        # Serve a precompressed copy on hosts with gzip_static support. Browsers
        # still request the GLB URL and transparently decode its response.
        with io.BytesIO(content) as source, target.with_suffix('.glb.gz').open('wb') as destination:
            with gzip.GzipFile(filename='', mode='wb', compresslevel=3,
                               fileobj=destination, mtime=0) as compressed:
                shutil.copyfileobj(source, compressed)
        return '/' + relative.as_posix()

    catalog = []
    for entry, path in entries:
        source = path.read_bytes()
        content = optimize_glb(source)
        entry['model_url'] = publish_model(entry['id'], 'model', content)
        entry['bytes'] = len(content)
        if entry.get('character_id') == 1030 and entry.get('costume') == '00':
            mascot = optimize_glb(source, {'anm_min_eve_type00_run00_loop'})
            entry['logo_model_url'] = publish_model(entry['id'], 'logo', mascot)
        catalog.append(entry)
    (output / 'api').mkdir()
    (output / 'api' / 'chibi-models').write_text(
        json.dumps({'models': catalog}, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8',
    )
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.local' / 'site',
                        help='New output directory (default: .local/site)')
    parser.add_argument('--models', type=Path, default=model_directory())
    args = parser.parse_args()
    try:
        catalog = build_site(args.output, args.models)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Build failed: {error}\n')
    print(f'Built {len(catalog)} outfits in {args.output.resolve()}')
    print(f'Model files: {sum(entry["bytes"] for entry in catalog):,} bytes')


if __name__ == '__main__':
    main()
