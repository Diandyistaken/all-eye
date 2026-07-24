#!/usr/bin/env bash
# All Eye - bash/Git Bash/WSL gunluk hook'u
#
# NOT: bash tarafinda komut CIKTISI yakalanmaz (PowerShell'de yakalaniyor).
# Cikti icin oturumu `script` altinda calistirmak gerekir ki bu her terminale
# bulasan bir cozum. Burada komut + cikis kodu + sure + dizin kaydedilir;
# mentor icin bu bile buyuk fark yaratir.

[ -n "$ALLEYE_HOOK_LOADED" ] && return 0
export ALLEYE_HOOK_LOADED=1

if [ -z "$ALLEYE_HOME" ]; then
  if [ -n "$LOCALAPPDATA" ]; then ALLEYE_HOME="$LOCALAPPDATA/AllEye"
  else ALLEYE_HOME="$HOME/.local/share/AllEye"; fi
fi
export ALLEYE_HOME
mkdir -p "$ALLEYE_HOME" 2>/dev/null

ALLEYE_JOURNAL="$ALLEYE_HOME/journal.jsonl"
ALLEYE_SESSION="$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n' 2>/dev/null || echo $$)"
ALLEYE_LAST=""
ALLEYE_START=0

_alleye_json() {
  # $1 metni JSON string govdesine cevirir (tirnaksiz)
  printf '%s' "$1" | python -c 'import json,sys; sys.stdout.write(json.dumps(sys.stdin.read())[1:-1])' 2>/dev/null \
    || printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\t/\\t/g' | tr -d '\r\n'
}

_alleye_preexec() {
  # DEBUG trap her komut oncesi calisir; PROMPT_COMMAND'in kendisini atla
  [ "$BASH_COMMAND" = "$PROMPT_COMMAND" ] && return
  case "$BASH_COMMAND" in _alleye_*) return ;; esac
  ALLEYE_LAST="$BASH_COMMAND"
  ALLEYE_START=$(date +%s%3N 2>/dev/null || date +%s000)
}

_alleye_prompt() {
  local code=$?
  [ -z "$ALLEYE_LAST" ] && return
  case "$ALLEYE_LAST" in alleye*|ae\ *|*"-m alleye"*) ALLEYE_LAST=""; return ;; esac
  local now dur ts cmd
  now=$(date +%s%3N 2>/dev/null || date +%s000)
  dur=$(( now - ALLEYE_START ))
  ts=$(date +%s)
  cmd=$(_alleye_json "$ALLEYE_LAST")
  printf '{"ts":%s,"session":"%s","shell":"bash","cwd":"%s","cmd":"%s","exit":%s,"dur_ms":%s,"out":"","truncated":false}\n' \
    "$ts" "$ALLEYE_SESSION" "$(_alleye_json "$PWD")" "$cmd" "$code" "$dur" >> "$ALLEYE_JOURNAL"
  ALLEYE_LAST=""
}

trap '_alleye_preexec' DEBUG
case "$PROMPT_COMMAND" in
  *_alleye_prompt*) ;;
  "") PROMPT_COMMAND="_alleye_prompt" ;;
  *)  PROMPT_COMMAND="_alleye_prompt; $PROMPT_COMMAND" ;;
esac

ae() { @@ALLEYE_CMD_SH@@ "$@"; }
