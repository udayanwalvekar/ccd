#!/usr/bin/env bash
# Runs the real ccd.sh in throwaway home folders: no terminal, piped, an update, someone else's ccd already there,
# a pyenv-style python3 shim first on PATH, a cut-short file. Never touches the real home, Keychain or claude.
# Run: bash tests/test_install.sh   (exits non-zero on the first failure)
set -euo pipefail
cd "$(dirname "$0")/.."
./build.sh >/dev/null
ROOT="$(mktemp -d "${TMPDIR:-/tmp}/ccd-install-test.XXXXXX")"
trap 'rm -rf "$ROOT"' EXIT
FAILED=0
ok()  { printf '  ok    %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILED=1; }
limit() { perl -e 'alarm shift; exec @ARGV' "$@"; }  # nothing may run away: 60 s at most

fresh() {  # a new home with a stand-in claude; prints its path
  local h="$ROOT/home-$1"
  mkdir -p "$h/.local/bin"
  printf '#!/bin/sh\necho "stand-in claude $*"\n' > "$h/.local/bin/claude"
  chmod +x "$h/.local/bin/claude"
  echo "$h"
}
run() {  # run a command in that home, with no terminal
  local h="$1"; shift
  case "$h" in "$ROOT"/*) ;; *) echo "refusing: $h is not a test home" >&2; exit 99 ;; esac
  limit 60 env -i HOME="$h" PATH="${EXTRA_PATH:-}$h/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin" \
    CCD_TOKEN_STORE=file CCD_SELF_UPDATE=0 ${CCD_NO_SETUP:+CCD_NO_SETUP=1} "$@" </dev/null 2>&1
}

echo "ccd.sh, in throwaway homes:"

H="$(fresh plain)"
out="$(run "$H" bash "$PWD/ccd.sh")" && [ -x "$H/.local/share/ccd/ccd" ] && [ -L "$H/.local/bin/ccdm" ] \
  && ok "bash ccd.sh installs (no terminal)" || bad "bash ccd.sh: $out"
v="$(run "$H" "$H/.local/bin/ccd" --version)" || true; [ "$v" = "ccd $(sed -n "s/^VERSION = '\(.*\)'$/\1/p" ccd)" ] \
  && ok "ccd --version answers ($v)" || bad "ccd --version: $v"
grep -q "is installed" <<<"$out" && ok "says what to do next" || bad "no closing words: $out"

H="$(fresh piped)"
out="$(run "$H" bash -c "cat '$PWD/ccd.sh' | bash; echo AFTER")" || true
grep -q AFTER <<<"$out" && [ -x "$H/.local/share/ccd/ccd" ] && ok "cat ccd.sh | bash installs and the shell carries on" \
  || bad "piped: $out"

mkdir -p "$H/.config/ccd" && printf '{"accounts":[{"key":"work","label":"Work","plan":200}]}' > "$H/.config/ccd/config.json"
printf '{"work":"sk-ant-oat01-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}' > "$H/.config/ccd/tokens.json"
out="$(CCD_NO_SETUP=1 run "$H" bash "$PWD/ccd.sh")" || true
grep -q '"Work"' "$H/.config/ccd/config.json" && grep -q work "$H/.config/ccd/tokens.json" \
  && ok "running it again (an update) keeps the accounts" || bad "update lost the accounts"
grep -q "is installed" <<<"$out" && bad "an update showed the welcome: $out" || ok "an update shows no welcome"

H="$(fresh foreign)"
printf '#!/bin/sh\ntouch "$HOME/FOREIGN-RAN"\n' > "$H/.local/bin/ccd" && chmod +x "$H/.local/bin/ccd"
out="$(run "$H" bash "$PWD/ccd.sh")" || true
[ ! -e "$H/FOREIGN-RAN" ] && ok "someone else's ccd is never run" || bad "the installer ran someone else's ccd"
grep -q "another program" <<<"$out" && [ ! -L "$H/.local/bin/ccd" ] && [ -L "$H/.local/bin/ccdm" ] \
  && ok "...left in place, and it says so" || bad "foreign ccd: $out"

H="$(fresh shim)"
mkdir -p "$H/shims"
REAL="$(command -v python3)"
printf '#!/usr/bin/env bash\nexec "%s" "$@"\n' "$REAL" > "$H/shims/python3" && chmod +x "$H/shims/python3"
out="$(EXTRA_PATH="$H/shims:" run "$H" bash "$PWD/ccd.sh")" || true
py="$(head -n 1 "$H/.local/share/ccd/ccd" 2>/dev/null | sed 's/^#!//; s/ -I$//' || true)"
[ -n "$py" ] && [ "$(head -c 2 "$py")" != '#!' ] && ok "a python3 shim first on PATH is not written into ccd ($py)" \
  || bad "with a shim first on PATH: ${py:-not installed}: $out"
v="$(EXTRA_PATH="$H/shims:" run "$H" "$H/.local/bin/ccd" --version)" || true
[ "${v#ccd }" != "$v" ] && ok "...and ccd runs" || bad "ccd under a shim: $v"

H="$(fresh cut)"
run "$H" bash "$PWD/ccd.sh" >/dev/null || true
before="$(shasum "$H/.local/share/ccd/ccd" 2>/dev/null || true)"
head -c 40000 ccd.sh > "$ROOT/cut.sh"
if run "$H" bash "$ROOT/cut.sh" >/dev/null; then bad "a cut-short file said it worked"; else ok "a cut-short file fails"; fi
[ -n "$before" ] && [ "$(shasum "$H/.local/share/ccd/ccd")" = "$before" ] && ok "...and changes nothing" || bad "a cut-short file changed ccd"

# ccd updating itself in the background runs with whatever PATH started the chat (a bot, a launchd job): it
# replaces the program and never touches the links or the shell's settings.
H="$(fresh program-only)"
run "$H" bash "$PWD/ccd.sh" >/dev/null || true
rm -f "$H/.local/bin/ccdm"  # a link the person removed
printf 'path+=(~/.local/bin)\n' > "$H/.zshrc" && cp "$H/.zshrc" "$ROOT/zshrc-before"
printf '#!/bin/sh\necho old\n' > "$H/.local/share/ccd/ccd"
out="$(limit 60 env -i HOME="$H" PATH="/usr/bin:/bin" CCD_TOKEN_STORE=file CCD_SELF_UPDATE=0 CCD_NO_SETUP=1 \
  CCD_PROGRAM_ONLY=1 bash "$PWD/ccd.sh" </dev/null 2>&1)" && code=0 || code=$?
v="$("$H/.local/share/ccd/ccd" --version 2>/dev/null </dev/null || true)"
[ "$code" = 0 ] && [ "${v#ccd }" != "$v" ] && ok "a background update replaces the program ($v)" || bad "program-only: $code $v $out"
cmp -s "$H/.zshrc" "$ROOT/zshrc-before" && [ ! -e "$H/.local/bin/ccdm" ] \
  && ok "...and leaves the links and the shell settings alone" || bad "program-only touched links or .zshrc: $(cat "$H/.zshrc")"

exit "$FAILED"
