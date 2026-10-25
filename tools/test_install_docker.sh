#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if ! command -v docker >/dev/null 2>&1; then
    printf '%s\n' 'docker is required for this acceptance test' >&2
    exit 1
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
git clone --bare "$root" "$work/repo.git" >/dev/null
git --git-dir="$work/repo.git" tag -f v1.0.0 >/dev/null

run_image() {
    image=$1
    setup='apt-get update >/dev/null && apt-get install -y --no-install-recommends git ca-certificates python3 python3-pip python3-venv >/dev/null'
    if [ "$image" = python:3.12-slim ]; then
        setup='apt-get update >/dev/null && apt-get install -y --no-install-recommends git ca-certificates >/dev/null'
    fi
    docker run --rm \
        -v "$root/install.sh:/work/install.sh:ro" \
        -v "$work/repo.git:/source/repo.git:ro" \
        "$image" sh -ec "
            $setup
            git config --global url.file:///source/repo.git.insteadOf https://github.com/zkasuran/gmi
            HOME=/root GMI_REF=v1.0.0 sh /work/install.sh --mcp
            test \"\$(HOME=/root /root/.local/bin/gmi --version)\" = 'gmi 1.0.0'
            HOME=/root /root/.local/bin/gmi mcp tools >/dev/null
        "
}

run_image python:3.12-slim
run_image debian:12
printf '%s\n' 'Docker installer acceptance passed for python:3.12-slim and debian:12.'
