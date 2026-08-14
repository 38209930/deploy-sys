#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${M1X_OSS_KEYCHAIN_SERVICE:-m1x-oss}"
ACCESS_KEY_ID="${M1X_OSS_ACCESS_KEY_ID:-}"
ACCESS_KEY_SECRET="${M1X_OSS_ACCESS_KEY_SECRET:-}"
REGION="${M1X_OSS_REGION:-oss-cn-beijing}"
BUCKET="${M1X_RESOURCE_OSS_BUCKET:-m1x-res}"
PUBLIC_DOMAIN="${M1X_RESOURCE_OSS_DOMAIN:-https://m1x-res.svision100.com}"

if [[ -z "$ACCESS_KEY_ID" ]]; then
  ACCESS_KEY_ID="$(security find-generic-password -s "$SERVICE_NAME" -a access-key-id -w 2>/dev/null || true)"
fi
if [[ -z "$ACCESS_KEY_SECRET" ]]; then
  ACCESS_KEY_SECRET="$(security find-generic-password -s "$SERVICE_NAME" -a access-key-secret -w 2>/dev/null || true)"
fi
if [[ -z "$ACCESS_KEY_ID" || -z "$ACCESS_KEY_SECRET" ]]; then
  echo "missing OSS credentials" >&2
  exit 1
fi

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
OBJECT_KEY="deploysys-probe/${RUN_ID}.txt"
BODY_FILE="$(mktemp)"
STATUS_FILE="$(mktemp)"
cleanup() {
  rm -f "$BODY_FILE" "$STATUS_FILE"
}
trap cleanup EXIT

printf 'm1x resource oss probe %s\n' "$RUN_ID" > "$BODY_FILE"

sign() {
  local method="$1"
  local content_type="$2"
  local date_header="$3"
  local resource="/${BUCKET}/${OBJECT_KEY}"
  local string_to_sign
  string_to_sign="${method}\n\n${content_type}\n${date_header}\n${resource}"
  printf '%b' "$string_to_sign" | openssl dgst -sha1 -hmac "$ACCESS_KEY_SECRET" -binary | openssl base64
}

request_oss() {
  local method="$1"
  local content_type="$2"
  local date_header
  local signature
  date_header="$(LC_ALL=C date -u '+%a, %d %b %Y %H:%M:%S GMT')"
  signature="$(sign "$method" "$content_type" "$date_header")"
  curl -sS -o "$STATUS_FILE" -w '%{http_code}' -X "$method" \
    -H "Date: ${date_header}" \
    -H "Content-Type: ${content_type}" \
    -H "Authorization: OSS ${ACCESS_KEY_ID}:${signature}" \
    --data-binary @"$BODY_FILE" \
    "https://${BUCKET}.${REGION}.aliyuncs.com/${OBJECT_KEY}"
}

put_status="$(request_oss PUT text/plain)"
if [[ "$put_status" != "200" ]]; then
  echo "PUT failed: HTTP ${put_status}" >&2
  exit 1
fi

public_status="$(curl -sS -o "$STATUS_FILE" -w '%{http_code}' "${PUBLIC_DOMAIN%/}/${OBJECT_KEY}")"
if [[ "$public_status" != "200" ]]; then
  echo "public GET failed: HTTP ${public_status}" >&2
  exit 1
fi

delete_date="$(LC_ALL=C date -u '+%a, %d %b %Y %H:%M:%S GMT')"
delete_signature="$(sign DELETE '' "$delete_date")"
delete_status="$(curl -sS -o "$STATUS_FILE" -w '%{http_code}' -X DELETE \
  -H "Date: ${delete_date}" \
  -H "Authorization: OSS ${ACCESS_KEY_ID}:${delete_signature}" \
  "https://${BUCKET}.${REGION}.aliyuncs.com/${OBJECT_KEY}")"
if [[ "$delete_status" != "204" ]]; then
  echo "DELETE failed: HTTP ${delete_status}; object=${OBJECT_KEY}" >&2
  exit 1
fi

verify_deleted="$(curl -sS -o "$STATUS_FILE" -w '%{http_code}' "${PUBLIC_DOMAIN%/}/${OBJECT_KEY}")"
if [[ "$verify_deleted" != "404" ]]; then
  echo "delete verification failed: HTTP ${verify_deleted}; object=${OBJECT_KEY}" >&2
  exit 1
fi

echo "bucket=${BUCKET}"
echo "object=${OBJECT_KEY}"
echo "public_get=200"
echo "deleted=204"
