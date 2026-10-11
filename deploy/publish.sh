#!/usr/bin/env bash
# Publish a validated static build without deleting files from older releases.
set -euo pipefail

source_dir=$(realpath -- "${1:?Usage: publish.sh BUILD_DIRECTORY RELEASE_NAME}")
release_name=${2:?Provide a unique release name}
base_dir=/var/www/chibi-studio

if [[ $EUID -ne 0 ]]; then
    echo 'Run this script with sudo.' >&2
    exit 1
fi
if [[ ! $release_name =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$ ]]; then
    echo 'Use letters, digits, hyphens and underscores in the release name.' >&2
    exit 1
fi
if [[ ! -f $source_dir/index.html || ! -f $source_dir/api/chibi-models ||
      ! -d $source_dir/assets || ! -d $source_dir/chibi-models ]]; then
    echo 'The source is not a complete Chibi Studio static build.' >&2
    exit 1
fi
if [[ -e $base_dir/releases/$release_name || -e $base_dir/.current-$release_name ||
      -L $base_dir/.current-$release_name ||
      ( -e $base_dir/current && ! -L $base_dir/current ) ]]; then
    echo 'The release already exists or the current deployment is not a symlink.' >&2
    exit 1
fi

install -d -m 755 "$base_dir" "$base_dir/shared" "$base_dir/shared/assets" \
    "$base_dir/shared/chibi-models" "$base_dir/releases" \
    "$base_dir/releases/$release_name" "$base_dir/releases/$release_name/api" \
    "$base_dir/releases/$release_name/chibi"

# Content hashes in these URLs make existing files immutable. Keep old versions
# so an already open studio can still fetch its modules, encoder and models.
rsync -rt --safe-links --ignore-existing --chmod=D755,F644 \
    "$source_dir/assets/" "$base_dir/shared/assets/"
rsync -rt --safe-links --ignore-existing --chmod=D755,F644 \
    "$source_dir/chibi-models/" "$base_dir/shared/chibi-models/"

install -m 644 "$source_dir/index.html" "$base_dir/releases/$release_name/index.html"
install -m 644 "$source_dir/index.html" "$base_dir/releases/$release_name/chibi/index.html"
install -m 644 "$source_dir/api/chibi-models" "$base_dir/releases/$release_name/api/chibi-models"
ln -s "releases/$release_name" "$base_dir/.current-$release_name"
mv -Tf "$base_dir/.current-$release_name" "$base_dir/current"
echo "Published Chibi Studio release $release_name"
