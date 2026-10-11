# Hosting Chibi Studio

Visitors only need a browser. Rendering, physics, local backgrounds and GIF
exports run on their device. The public site can be entirely static.

## Build

With the complete character library available, run:

```sh
python build_static.py --output .local/site
```

Use a new output directory for each build. The builder checks the model
manifests and rejects missing Git LFS data. It includes only the browser
assets, models and generated character catalog. Exporter settings, source
code, tests and private configuration are excluded.

The generated `api/chibi-models` file is JSON; it does not require a running
API server. Models and browser assets have content hashes in their URLs so
they can be cached until their content changes. HTML and the catalog should
be revalidated on each visit.

The build also writes precompressed `.glb.gz` copies beside the models. The
included Nginx configuration serves these when the browser accepts gzip,
reducing downloads without changing the model URLs or decoded files. Other
static hosts can serve the original GLBs, or enable the equivalent gzip
support. Nginx needs its `http_gzip_static_module` for the supplied snippet.

## Nginx on a VPS

The files under `deploy/` use this layout:

```text
/var/www/chibi-studio/
  acme/                  Certificate validation files
  current -> releases/release-001
  releases/release-001/   HTML and character catalog
  shared/assets/         Versioned browser assets
  shared/chibi-models/   Versioned character files
```

Upload the static build and `deploy/` files to a staging directory on the
server. After verifying the uploaded files, publish with:

```sh
sudo bash deploy/publish.sh /path/to/uploaded/site release-001
```

The publisher adds the versioned files, then switches the current release
atomically. Existing assets and releases are retained, including assets
needed by visitors who already have the studio open.

Install `deploy/nginx-content.conf` as
`/etc/nginx/snippets/chibi-studio-content.conf`. Use a dedicated Nginx site
for the chosen hostname. For initial certificate validation, its HTTP server
block should serve `/.well-known/acme-challenge/` from
`/var/www/chibi-studio/acme` and include the content snippet for other routes.

With DNS pointing to the server and HTTP working, obtain a certificate using
the existing Certbot installation and account:

```sh
sudo certbot certonly --webroot -w /var/www/chibi-studio/acme -d chibi.example.com
```

Replace `chibi.example.com` in `deploy/nginx-site.conf` with the real hostname,
install it as the site's configuration, and run `sudo nginx -t` before
reloading Nginx. Configure a Certbot deploy hook to validate and reload Nginx
when this site's certificate renews. Keep the existing server's other sites
and certificate settings intact.

For later releases, repeat the build, upload, verification and publication
steps with a new release name. Nginx does not need to restart for content
updates. To roll back, atomically point `current` to a retained release.
Only remove old versioned assets when no retained release refers to them.

## Cloudflare

Point the hostname's A record to the VPS. Verify the origin certificate
before enabling the proxy. Use **Full (strict)** encryption for this
hostname; if other sites need a different setting, use a hostname-specific
configuration rule instead of changing the entire zone.

Cloudflare does not cache `.glb` by default. For model caching, create a Cache
Rule matching this hostname and `/chibi-models/`, mark it eligible for cache,
and respect the origin's Cache-Control header. The versioned URLs permit
long caching without hiding updated models. Keep `/api/chibi-models` and
HTML uncached at the edge so the current library appears after publication.

Cloudflare's ordinary CDN and its developer storage products have different
delivery terms. For a library with substantial model traffic, models can be
served from R2 while the site remains on the VPS.

- [Cloudflare cache defaults](https://developers.cloudflare.com/cache/concepts/default-cache-behavior/)
- [Cloudflare CDN terms](https://www.cloudflare.com/service-specific-terms-application-services/)
- [Certbot webroot setup](https://eff-certbot.readthedocs.io/en/stable/using.html#webroot)

## Check a deployment

Set `CHIBI_STUDIO_URL` to the site's HTTPS URL and run
`tests/check_chibi_studio.py` using the development environment. It checks
actual GIF frames and transparency, custom backgrounds, stage changes,
export cancellation, saved settings and mobile layout.

Also check the catalog, model downloads, content types, cache headers, HTTPS
redirects and automatic certificate renewal on the live host.
