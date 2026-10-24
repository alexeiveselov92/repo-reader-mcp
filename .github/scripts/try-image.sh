#!/usr/bin/env bash
# Tries the server's image the way a deployment runs it: read-only, without rights, mirroring this repository by https.
# It must become ready, refuse a call without the token, and read a file with it.
#
#   .github/scripts/try-image.sh IMAGE [PLATFORM]      # PLATFORM: linux/amd64 (the default) or linux/arm64
set -euo pipefail
image=$1
platform=${2:-linux/amd64}
url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-alexeiveselov92/repo-reader-mcp}"

config=$(mktemp -d)
chmod 755 "$config"  # the server's user reads it
printf 'repositories:\n  - name: self\n    url: %s\n    refs: [main]\nhttp:\n  token_env: TRY_TOKEN\n' "$url" \
  > "$config/config.yaml"
chmod 644 "$config/config.yaml"

docker run -d --name try --platform "$platform" --read-only --tmpfs /tmp --cap-drop ALL \
  --security-opt no-new-privileges -v "$config:/config:ro" -e TRY_TOKEN=made-up-token \
  -p 127.0.0.1:8000:8000 "$image" >/dev/null
trap 'docker logs try; docker rm -fv try >/dev/null; rm -rf "$config"' EXIT

for _ in $(seq 120); do
  curl -fsS http://127.0.0.1:8000/health && break
  sleep 1
done
curl -fsS http://127.0.0.1:8000/health | grep -q '"ready"'
test "$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8000/mcp)" = 401
curl -fsS -X POST http://127.0.0.1:8000/mcp -H 'Authorization: Bearer made-up-token' \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":"try","method":"tools/call","params":{"name":"read_file","arguments":{"repo":"self","path":"LICENSE"}}}' \
  | grep -q 'Apache License'
echo
echo "the image works on $platform ($(docker run --rm --platform "$platform" --entrypoint uname "$image" -m))"
