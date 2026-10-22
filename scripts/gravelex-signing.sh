#!/usr/bin/env bash
# Private signing material is stored outside the checkout; never print its values.
set +x
set -euo pipefail
umask 077
signing_dir="${GRAVELEX_SIGNING_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/gravelex/signing}"
repo="${GRAVELEX_REPOSITORY:-icewall905/pebble-app-degoogled}"
case "${1:-}" in
  generate)
    mkdir -p "$signing_dir"
    chmod 700 "$signing_dir"
    if [[ -e "$signing_dir/release.jks" ]]; then
      for item in store-password key-password key-alias; do
        test -s "$signing_dir/$item" || { echo "Existing key has missing metadata; restore its backup." >&2; exit 1; }
      done
      echo "Existing signing key retained: $signing_dir/release.jks"
    else
      # Fail closed on partial state: never silently replace a release identity.
      for item in store-password key-password key-alias; do
        test ! -e "$signing_dir/$item" || { echo "Partial signing state; inspect before retrying." >&2; exit 1; }
      done
      openssl rand -hex 32 > "$signing_dir/store-password"
      openssl rand -hex 32 > "$signing_dir/key-password"
      printf '%s\n' gravelex > "$signing_dir/key-alias"
      export GRAVELEX_STORE_PASSWORD="$(cat "$signing_dir/store-password")"
      export GRAVELEX_KEY_PASSWORD="$(cat "$signing_dir/key-password")"
      keytool -genkeypair -keystore "$signing_dir/release.jks" -storetype JKS \
        -alias gravelex -keyalg RSA -keysize 3072 -validity 10000 \
        -dname 'CN=GravelEx, OU=Personal Apps, O=TDGS' \
        -storepass:env GRAVELEX_STORE_PASSWORD -keypass:env GRAVELEX_KEY_PASSWORD
      unset GRAVELEX_KEY_PASSWORD GRAVELEX_STORE_PASSWORD
    fi
    export GRAVELEX_STORE_PASSWORD="$(cat "$signing_dir/store-password")"
    keytool -exportcert -keystore "$signing_dir/release.jks" -alias "$(cat "$signing_dir/key-alias")" \
      -storepass:env GRAVELEX_STORE_PASSWORD -file "$signing_dir/release-cert.der"
    unset GRAVELEX_STORE_PASSWORD
    openssl x509 -inform DER -in "$signing_dir/release-cert.der" -noout -fingerprint -sha256 | tee "$signing_dir/certificate-sha256.txt"
    echo "Back up the entire private directory securely: $signing_dir"
    ;;
  upload)
    gh_bin="${GH_BIN:-gh}"
    script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    expected="$(tr -d '\r\n' < "$script_root/docs/gravelex-signing-sha256.txt")"
    actual="$(openssl x509 -inform DER -in "$signing_dir/release-cert.der" -noout -fingerprint -sha256 | cut -d= -f2 | tr -d ':' | tr 'A-F' 'a-f')"
    [[ "$expected" =~ ^[a-f0-9]{64}$ && "$actual" == "$expected" ]] || {
      echo "Signing certificate does not match the pinned release identity. Restore the original key; see GRAVELEX.md." >&2
      exit 1
    }
    "$gh_bin" auth status --hostname github.com
    for item in release.jks store-password key-password key-alias; do test -s "$signing_dir/$item"; done
    base64 -w 0 "$signing_dir/release.jks" | "$gh_bin" secret set GRAVELEX_KEYSTORE_BASE64 --repo "$repo"
    "$gh_bin" secret set GRAVELEX_KEYSTORE_PASSWORD --repo "$repo" < "$signing_dir/store-password"
    "$gh_bin" secret set GRAVELEX_KEY_ALIAS --repo "$repo" < "$signing_dir/key-alias"
    "$gh_bin" secret set GRAVELEX_KEY_PASSWORD --repo "$repo" < "$signing_dir/key-password"
    echo "Four signing secrets configured for $repo."
    ;;
  fingerprint)
    openssl x509 -inform DER -in "$signing_dir/release-cert.der" -noout -fingerprint -sha256
    ;;
  *) echo "Usage: $0 {generate|upload|fingerprint}" >&2; exit 2 ;;
esac
