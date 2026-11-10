#!/bin/bash
# The pinned `age` (https://age-encryption.org) that encrypts backups (#356, D-92).
#   age-tool.sh install   download the release for this OS/CPU into ~/.capitalos/age/<version>/,
#                         checked against the sha256 below (no-op when already there)
#   age-tool.sh path      print the age binary's path (AGE_BIN overrides); fails if not installed
#   age-tool.sh keygen-path   the same for age-keygen
# A binary, not an image: backups run on the host (launchd), and age reads the private key from a
# file outside the repo, which a container would need mounted. The checksums are GitHub's own
# asset digests for the release, checked when pinned; a bump changes VERSION and all four.
set -euo pipefail

VERSION=v1.3.2
DIR=${CAPITALOS_AGE_DIR:-$HOME/.capitalos/age}/$VERSION

sha_for() {
  case "$1" in
    darwin-arm64) echo e2020b073c44f692685a24d6abc378817eb81ffaaf49fd0531ef8565f767f2f5 ;;
    darwin-amd64) echo 1d1e4bc66e1427edad7739ae7616157de0e79db8b6d2a1497d7d9925fb06a539 ;;
    linux-amd64) echo cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10 ;;
    linux-arm64) echo 6b8dc4333c53a5a57c9e5834e3a48f92605d7154014cd07269ff3327db5d37f4 ;;
    *) return 1 ;;
  esac
}

platform() {
  local os arch
  os=$(uname -s | tr '[:upper:]' '[:lower:]')
  arch=$(uname -m)
  case "$arch" in x86_64) arch=amd64 ;; aarch64 | arm64) arch=arm64 ;; esac
  echo "$os-$arch"
}

sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -c1-64; else shasum -a 256 "$1" | cut -c1-64; fi; }

install() {
  local p want tmp got
  if [ -x "$DIR/age" ] && [ -x "$DIR/age-keygen" ]; then echo "age $VERSION ready: $DIR/age"; return 0; fi
  p=$(platform)
  want=$(sha_for "$p") || { echo "age-tool: no pinned age build for $p" >&2; return 1; }
  tmp=$(mktemp -d)
  if ! curl -fsSL -o "$tmp/age.tgz" "https://github.com/FiloSottile/age/releases/download/$VERSION/age-$VERSION-$p.tar.gz"; then
    rm -rf "$tmp"; echo "age-tool: download of age $VERSION $p failed" >&2; return 1
  fi
  got=$(sha256 "$tmp/age.tgz")
  if [ "$got" != "$want" ]; then
    rm -rf "$tmp"; echo "age-tool: checksum mismatch for age $VERSION $p (got $got, pinned $want); nothing installed" >&2; return 1
  fi
  tar -xzf "$tmp/age.tgz" -C "$tmp"
  mkdir -p "$DIR"
  cp "$tmp/age/age" "$tmp/age/age-keygen" "$DIR/"
  chmod 755 "$DIR/age" "$DIR/age-keygen"
  rm -rf "$tmp"
  echo "age $VERSION installed: $DIR/age (sha256 checked)"
}

path_of() {  # <binary>
  local override=""
  [ "$1" = age ] && override=${AGE_BIN:-}
  [ "$1" = age-keygen ] && override=${AGE_KEYGEN_BIN:-}
  if [ -n "$override" ]; then echo "$override"; return 0; fi
  [ -x "$DIR/$1" ] || { echo "age-tool: $1 $VERSION is not installed: run make host-tools (or scripts/age-tool.sh install)" >&2; return 1; }
  echo "$DIR/$1"
}

case "${1:-}" in
  install) install ;;
  path) path_of age ;;
  keygen-path) path_of age-keygen ;;
  *) echo "usage: $0 install|path|keygen-path" >&2; exit 2 ;;
esac
