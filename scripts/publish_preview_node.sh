#!/usr/bin/env bash
set -euo pipefail
tag=sqlite-default
repo="${GITHUB_REPOSITORY:?}"
sha="${GITHUB_SHA:?}"
bash -n install.sh
(cd dist && sha256sum -c gost-amd64.sha256)
# A branch preview is a rolling prerelease, not a stable version or GitHub latest.
if ! gh release view "$tag" --repo "$repo" >/dev/null 2>&1; then
    gh release create "$tag" --repo "$repo" --target "$sha" --prerelease --latest=false \
        --title "Flux Panel SQLite preview (node)" --notes "Linux AMD64 preview assets are being prepared for $sha"
fi
gh release upload "$tag" install.sh dist/gost-amd64 dist/gost-amd64.sha256 --clobber --repo "$repo"
# Check the real published assets before allowing container image publication.
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
gh release download "$tag" --repo "$repo" --dir "$scratch" --pattern install.sh --pattern gost-amd64 --pattern gost-amd64.sha256
cmp install.sh "$scratch/install.sh"
cmp dist/gost-amd64.sha256 "$scratch/gost-amd64.sha256"
(cd "$scratch" && sha256sum -c gost-amd64.sha256)

# Mark the exact revision ready only after all uploaded assets have been verified.
gh release edit "$tag" --repo "$repo" --prerelease --latest=false \
    --notes "Rolling Linux AMD64 node build. verified-build=$sha. Installer and binary are published together. Use matching SQLite preview panel images."
