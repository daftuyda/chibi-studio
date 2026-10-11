"""Serve Chibi Studio and its included character library. Python 3.10+, no packages."""
import argparse
import json
import mimetypes
import os
import re
import shutil
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
MODEL_ID = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}')


def read_model(root, ident):
    if not MODEL_ID.fullmatch(ident):
        return None
    try:
        folder = (root / ident).resolve()
        manifest = (folder / 'manifest.json').resolve()
        if not folder.is_relative_to(root) or not manifest.is_relative_to(folder) or manifest.stat().st_size > 65536:
            return None
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('model'), str):
            return None
        relative = Path(data['model'])
        if relative.is_absolute() or relative.drive or '..' in relative.parts:
            return None
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder) or path.suffix.lower() != '.glb' or not path.is_file():
            return None
        with path.open('rb') as source:
            if source.read(4) != b'glTF':
                return None
        region = 'jp' if data.get('region') == 'jp' else 'global'
        available_in = data.get('available_in')
        if not isinstance(available_in, list):
            available_in = [region]
        entry = {
            'id': ident,
            'region': region,
            'available_in': [value for value in ('global', 'jp') if value in available_in],
            'character_id': data.get('character_id') if isinstance(data.get('character_id'), int) else None,
            'costume': str(data.get('costume') or '00')[:20],
            'dress_id': data.get('dress_id') if isinstance(data.get('dress_id'), int) else None,
            'name': str(data.get('name') or ident)[:120],
            'outfit': str(data.get('outfit') or 'Local outfit')[:120],
            'name_jp': str(data.get('name_jp') or '')[:120],
            'outfit_jp': str(data.get('outfit_jp') or '')[:120],
            'model_url': f'/chibi-models/{ident}/model.glb',
            'bytes': path.stat().st_size,
            'animation_labels': data.get('animation_labels') if isinstance(data.get('animation_labels'), dict) else {},
            'animation_groups': data.get('animation_groups') if isinstance(data.get('animation_groups'), dict) else {},
            'faces': data.get('faces') if isinstance(data.get('faces'), dict) else {},
        }
        entry['display_name'] = f"{entry['name']} — {entry['outfit']}"
        return entry, path
    except (OSError, ValueError, TypeError, RuntimeError):
        return None


class ViewerHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, web, models, **kwargs):
        self.web, self.models = web.resolve(), models.resolve()
        super().__init__(*args, **kwargs)

    def do_GET(self):
        self.respond(False)

    def do_HEAD(self):
        self.respond(True)

    def headers_for(self, length, content_type):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()

    def file_response(self, path, head):
        try:
            with path.open('rb') as source:
                content_type = {'.js': 'text/javascript', '.glb': 'model/gltf-binary'}.get(path.suffix)
                content_type = content_type or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
                self.headers_for(os.fstat(source.fileno()).st_size, content_type)
                if not head:
                    shutil.copyfileobj(source, self.wfile)
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Switching outfits can cancel the previous download.

    def respond(self, head):
        route = unquote(urlsplit(self.path).path)
        if route in ('/', '/chibi'):
            return self.file_response(self.web / 'chibi-viewer.html', head)
        if route == '/api/chibi-models':
            entries = []
            if self.models.is_dir():
                entries = [result[0] for folder in sorted(self.models.iterdir())
                           if folder.is_dir() and (result := read_model(self.models, folder.name))]
            payload = json.dumps({'models': entries}, ensure_ascii=False).encode('utf-8')
            self.headers_for(len(payload), 'application/json; charset=utf-8')
            if not head:
                self.wfile.write(payload)
            return
        match = re.fullmatch(r'/chibi-models/([^/]+)/model\.glb', route)
        if match:
            result = read_model(self.models, match[1])
            if result:
                return self.file_response(result[1], head)
        if route.startswith('/assets/'):
            try:
                asset = (self.web / route.removeprefix('/assets/')).resolve()
                if asset.is_relative_to(self.web) and asset.is_file():
                    return self.file_response(asset, head)
            except (OSError, ValueError):
                pass
        self.send_error(404)


def model_directory():
    return Path(os.environ.get('CHIBI_MODELS_DIR') or ROOT / 'models')


def make_server(host='127.0.0.1', port=8084, models=None, web=None):
    handler = partial(ViewerHandler, web=web or ROOT / 'web', models=models if models is not None else model_directory())
    return ThreadingHTTPServer((host, port), handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8084)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--models', type=Path, default=model_directory(), help='Character library directory (default: models/ beside viewer.py)')
    args = parser.parse_args()
    server = make_server(args.host, args.port, args.models)
    print(f'Chibi Studio: http://{args.host}:{server.server_port}', flush=True)
    print(f'Character library: {args.models.resolve()}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
