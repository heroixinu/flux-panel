#!/usr/bin/env bash
# Run without touching the host's /etc/gost or systemd.
set -euo pipefail
cd "$(dirname "$0")/.."
bash -n install.sh
source ./install.sh
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
INSTALL_DIR="$scratch/target"
mkdir "$INSTALL_DIR"
export FLUX_REPO=heroixinu/flux-panel FLUX_RELEASE_TAG=sqlite-default
ARCH_FIXTURE=x86_64
uname() { printf '%s\n' "$ARCH_FIXTURE"; }
curl() {
    local arg url="" out=""
    while (($#)); do
        case "$1" in
            -o) out="$2"; shift 2 ;;
            --max-time|--retry) shift 2 ;;
            https://*) url="$1"; shift ;;
            *) shift ;;
        esac
    done
    case "$url" in
        https://ipinfo.io/country) printf 'US\n' ;;
        "$DOWNLOAD_URL") [[ "$FAIL_DOWNLOAD" == 0 ]] && cp "$scratch/source" "$out" ;;
        "$DOWNLOAD_URL.sha256") cp "$scratch/checksum" "$out" ;;
        *) echo "unexpected download URL" >&2; return 1 ;;
    esac
}
configure_download
[[ "$DOWNLOAD_URL" == https://github.com/heroixinu/flux-panel/releases/download/sqlite-default/gost-amd64 ]]
FLUX_RELEASE_TAG=1.5.0
configure_download
[[ "$DOWNLOAD_URL" == https://github.com/heroixinu/flux-panel/releases/download/1.5.0/gost-amd64 ]]
ARCH_FIXTURE=aarch64
if build_download_url; then echo "unexpected ARM64 success" >&2; exit 1; fi
ARCH_FIXTURE=x86_64
FLUX_RELEASE_TAG='bad;tag'
if build_download_url; then echo "unexpected invalid tag success" >&2; exit 1; fi
FLUX_RELEASE_TAG=sqlite-default
configure_download
printf 'new-node-binary' > "$scratch/source"
sha256sum "$scratch/source" > "$scratch/checksum"
FAIL_DOWNLOAD=0
printf 'old' > "$INSTALL_DIR/gost"
download_gost "$INSTALL_DIR/gost"
cmp "$scratch/source" "$INSTALL_DIR/gost"
printf 'installed-node' > "$INSTALL_DIR/gost"
printf '%064d  gost-amd64\n' 0 > "$scratch/checksum"
if download_gost "$INSTALL_DIR/gost"; then echo "checksum error accepted" >&2; exit 1; fi
[[ "$(cat "$INSTALL_DIR/gost")" == installed-node ]]
FAIL_DOWNLOAD=1
if download_gost "$INSTALL_DIR/gost"; then echo "failed download accepted" >&2; exit 1; fi
[[ "$(cat "$INSTALL_DIR/gost")" == installed-node ]]
[[ -z "$(find "$INSTALL_DIR" -name '.gost-download.*' -print)" ]]
echo "Node installer release selection, SHA256 verification and failure preservation passed"
