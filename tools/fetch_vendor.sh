#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
target="$project_dir/vendor/Kanata_S_Wireless_WG9S_Software_V1.0.0.42_24081600.exe"
if [[ -e "$target" ]]; then
    printf 'Already exists: %s\n' "$target"
    exit 0
fi
mkdir -p "$project_dir/vendor"
temporary="$(mktemp "$project_dir/vendor/download.XXXXXX")"
trap 'rm -f -- "$temporary"' EXIT
curl --fail --location --proto '=https' --proto-redir '=https' \
    'https://cdn.shopify.com/s/files/1/0630/1689/4649/files/Kanata_S_Wireless_WG9S_Software_V1.0.0.42_24081600.exe?v=1726041306' \
    --output "$temporary"
[[ "$(head -c 2 "$temporary")" == MZ ]] || { echo 'Not a Windows executable' >&2; exit 1; }
mv -- "$temporary" "$target"
sha256sum "$target" > "$target.sha256"
printf 'Downloaded for static analysis; nothing has been executed.\n%s\n' "$target"
