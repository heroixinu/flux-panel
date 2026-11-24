#!/usr/bin/env bash
# The independent Native workflow must not publish a panel whose node assets
# are absent or from an older preview revision.
set -euo pipefail
repo="${GITHUB_REPOSITORY:?}"
tag=sqlite-default
preview=true
if [[ "${GITHUB_REF:?}" == refs/tags/* ]]; then
    tag="${GITHUB_REF_NAME:?}"
    preview=false
fi
for _ in $(seq 1 120); do
    if info=$(gh release view "$tag" --repo "$repo" --json assets,body,isDraft 2>/dev/null) &&
       jq -e --arg marker "verified-build=$GITHUB_SHA." --argjson preview "$preview" '
         (.isDraft == false) and
         (([.assets[].name] | contains(["install.sh","gost-amd64","gost-amd64.sha256"]))) and
         (($preview | not) or (.body | contains($marker)))
       ' <<< "$info" >/dev/null; then
        echo "Node release $tag is ready for $GITHUB_SHA"
        exit 0
    fi
    sleep 5
done
echo "Matching node release not available; refusing to publish Native panel" >&2
exit 1
