#!/usr/bin/env bash
# Manual reproduction matrix for the Claude Code x RTK worktree-isolation interaction.
# Not run in CI: it drives headless `claude -p` sessions (network, model cost, ~minutes) and
# is meant as a regression check whenever Claude Code or RTK is upgraded.
#
# Usage: scripts/rtk-worktree-matrix.sh [--plugin-dir DIR] [--configs c0,c1,...] [--model M] [--keep]
#
# Each config runs two headless sessions in a throwaway repo: one with the rewrite-prone git
# spellings, one with the RTK_DISABLED=1 escape-hatch spellings. After EnterWorktree every Bash
# call is classified and the result is printed as a matrix.
#
#   c0  your real settings (RTK hook + whatever plugins you have installed)
#   c1  Claude Code + RTK hook only
#   c2  Claude Code only
#   c3  Claude Code + this plugin (--plugin-dir), no RTK
#   c4  Claude Code + RTK hook + this plugin (--plugin-dir)   <- end-to-end for the hook
#
# Cells: ALLOW, CC-CONTAINMENT / CC-COMPLEXITY (Claude Code's own refusal), PLUGIN-HOOK (this
# plugin's rtk_worktree_guard deny), ERROR, MISSING (the session never ran that command).
#
# Cleanup: everything lives under one mktemp root. On exit (also INT/TERM) every
# `.claude/worktrees/*` worktree the sessions created is removed and pruned, the root is
# deleted, the project dirs those runs registered under `${CLAUDE_CONFIG_DIR:-~/.claude}/projects`
# (matched by this run's unique root suffix) are removed, and the root's absence is verified.
# --keep skips all of that and prints the root path.
set -uo pipefail

if [ $# -ge 1 ] && { [ "$1" = "--help" ] || [ "$1" = "-h" ]; }; then
  awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' "$0"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIGS="c0,c1,c2,c3,c4"
MODEL="sonnet"
KEEP=0
SOURCES="project,local" # exclude user-level settings so each config is hermetic

while [ $# -gt 0 ]; do
  case "$1" in
    --plugin-dir) PLUGIN_DIR="${2:?--plugin-dir needs a value}"; shift 2 ;;
    --configs) CONFIGS="${2:?--configs needs a value}"; shift 2 ;;
    --model) MODEL="${2:?--model needs a value}"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    *) echo "rtk-worktree-matrix: unknown argument: $1" >&2; exit 64 ;;
  esac
done

for tool in claude git python3; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "rtk-worktree-matrix: required tool not found: $tool" >&2
    exit 2
  fi
done

ROOT=""
CLEANED=0

cleanup() {
  [ "$CLEANED" -eq 0 ] || return 0
  CLEANED=1
  [ -n "$ROOT" ] || return 0
  if [ "$KEEP" -eq 1 ]; then
    echo "rtk-worktree-matrix: kept scratch root: $ROOT"
    return 0
  fi
  case "$ROOT" in
    */rtk-wt-matrix.*) ;;
    *) echo "rtk-worktree-matrix: refusing to delete unexpected root: $ROOT" >&2; return 0 ;;
  esac
  local repo wt
  for repo in "$ROOT"/*/; do
    [ -d "${repo}.git" ] || continue
    while IFS= read -r wt; do
      git -C "$repo" worktree remove --force "$wt" >/dev/null 2>&1 || true
    done < <(git -C "$repo" worktree list --porcelain 2>/dev/null \
      | sed -n 's/^worktree //p' | grep -F '/.claude/worktrees/')
    git -C "$repo" worktree prune >/dev/null 2>&1 || true
  done
  rm -rf "$ROOT"
  # Each headless run also registers a project dir (and a worktree twin) in the user's Claude
  # config dir, keyed by the cwd path. Remove only those carrying this run's unique suffix.
  local suffix="${ROOT##*rtk-wt-matrix.}" projects proj
  projects="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects"
  if [[ "$suffix" =~ ^[A-Za-z0-9]{6}$ ]] && [ -d "$projects" ]; then
    for proj in "$projects"/*"rtk-wt-matrix-${suffix}-"*; do
      [ -d "$proj" ] && rm -rf "$proj"
    done
  fi
  if [ -e "$ROOT" ]; then
    echo "rtk-worktree-matrix: WARNING: scratch root still exists: $ROOT" >&2
    exit 1
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/rtk-wt-matrix.XXXXXX")" || {
  echo "rtk-worktree-matrix: could not create a scratch root" >&2
  exit 2
}

cat >"$ROOT/rtk-only.json" <<'EOF'
{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"rtk hook claude"}]}]}}
EOF

HEADER='You are a test harness executor. Follow these steps EXACTLY. Do not reword, retry, combine, or work around any command. If a command is refused or errors, just record it and move on. Each lettered command is ONE separate Bash tool call, typed verbatim.

Step 1: Call the EnterWorktree tool with name "probe". Note the absolute worktree path it reports; below, <WT> means that absolute path typed literally (no shell variables).

Step 2: Run each of these as its own Bash call, in order:'

cat >"$ROOT/prompt-rewrite.md" <<EOF
${HEADER}
  R1: git status
  R2: git -C <WT> status
  R3: rtk git status
  R4: rtk proxy git status
  R5: /usr/bin/git status
  R6: git status && git log -1 --oneline
  M1: git commit --allow-empty -m probe-m1
  M2: git -C <WT> commit --allow-empty -m probe-m2
  M3: rtk git commit --allow-empty -m probe-m3
  M4: /usr/bin/git commit --allow-empty -m probe-m4
  M5: git add -A && git commit --allow-empty -m probe-m5
  W1: time git status
  W2: command git status

Step 3: Reply with just "DONE".
EOF

cat >"$ROOT/prompt-disabled.md" <<EOF
${HEADER}
  D1: RTK_DISABLED=1 git status
  D2: RTK_DISABLED=1 git -C <WT> status
  D3: RTK_DISABLED=1 git commit --allow-empty -m probe-d3
  D4: RTK_DISABLED=1 git status && RTK_DISABLED=1 git log -1 --oneline
  D5: RTK_DISABLED=1 git add -A && RTK_DISABLED=1 git commit --allow-empty -m probe-d5
  D6: env RTK_DISABLED=1 git status
  D7: export RTK_DISABLED=1; git status
  D8: ls && RTK_DISABLED=1 git status
  D9: RTK_DISABLED=1 git commit --allow-empty -m "probe d9"
  D10: RTK_DISABLED=1 git log -1 --format="%h %s"

Step 3: Reply with just "DONE".
EOF

run_session() { # <config> <rewrite|disabled>
  local cfg="$1" which="$2" dir="$ROOT/$1-$2"
  mkdir -p "$dir"
  git -C "$dir" init -q
  printf '.claude/\n' >"$dir/.gitignore"
  printf 'probe\n' >"$dir/README"
  git -C "$dir" add -A
  git -C "$dir" -c user.name=probe -c user.email=probe@example.invalid commit -q -m init

  local -a extra=()
  case "$cfg" in
    c0) ;;
    c1) extra=(--setting-sources "$SOURCES" --settings "$ROOT/rtk-only.json") ;;
    c2) extra=(--setting-sources "$SOURCES") ;;
    c3) extra=(--setting-sources "$SOURCES" --plugin-dir "$PLUGIN_DIR") ;;
    c4) extra=(--setting-sources "$SOURCES" --settings "$ROOT/rtk-only.json" --plugin-dir "$PLUGIN_DIR") ;;
    *) echo "rtk-worktree-matrix: unknown config: $cfg" >&2; return 64 ;;
  esac

  echo "running $cfg/$which ..." >&2
  (
    cd "$dir" || exit 1
    GIT_AUTHOR_NAME=probe GIT_AUTHOR_EMAIL=probe@example.invalid \
      GIT_COMMITTER_NAME=probe GIT_COMMITTER_EMAIL=probe@example.invalid \
      claude --print --model "$MODEL" --output-format stream-json --verbose \
        --allowedTools "Bash,EnterWorktree" ${extra[@]+"${extra[@]}"} \
        <"$ROOT/prompt-$which.md" >"$ROOT/$cfg-$which.jsonl" 2>"$ROOT/$cfg-$which.err"
  )
}

IFS=',' read -r -a CFG_LIST <<<"$CONFIGS"
for cfg in "${CFG_LIST[@]}"; do
  run_session "$cfg" rewrite
  run_session "$cfg" disabled
done

python3 -I - "$ROOT" "$CONFIGS" <<'PY'
import json
import re
import sys
from pathlib import Path

root, configs = Path(sys.argv[1]), sys.argv[2].split(",")

STEPS = [
    ("R1", "git status"),
    ("R2", "git -C <WT> status"),
    ("R3", "rtk git status"),
    ("R4", "rtk proxy git status"),
    ("R5", "/usr/bin/git status"),
    ("R6", "git status && git log -1 --oneline"),
    ("M1", "git commit --allow-empty -m probe-m1"),
    ("M2", "git -C <WT> commit --allow-empty -m probe-m2"),
    ("M3", "rtk git commit --allow-empty -m probe-m3"),
    ("M4", "/usr/bin/git commit --allow-empty -m probe-m4"),
    ("M5", "git add -A && git commit --allow-empty -m probe-m5"),
    ("W1", "time git status"),
    ("W2", "command git status"),
    ("D1", "RTK_DISABLED=1 git status"),
    ("D2", "RTK_DISABLED=1 git -C <WT> status"),
    ("D3", "RTK_DISABLED=1 git commit --allow-empty -m probe-d3"),
    ("D4", "RTK_DISABLED=1 git status && RTK_DISABLED=1 git log -1 --oneline"),
    ("D5", "RTK_DISABLED=1 git add -A && RTK_DISABLED=1 git commit --allow-empty -m probe-d5"),
    ("D6", "env RTK_DISABLED=1 git status"),
    ("D7", "export RTK_DISABLED=1; git status"),
    ("D8", "ls && RTK_DISABLED=1 git status"),
    ("D9", 'RTK_DISABLED=1 git commit --allow-empty -m "probe d9"'),
    ("D10", 'RTK_DISABLED=1 git log -1 --format="%h %s"'),
]
PATTERNS = [
    (sid, re.compile(re.escape(tpl).replace(re.escape("<WT>"), r"\S+")))
    for sid, tpl in STEPS
]


def classify(text, is_error):
    if "BLOCKED [rtk-worktree" in text:
        return "PLUGIN-HOOK"
    if "too complex to verify" in text:
        return "CC-COMPLEXITY"
    if any(s in text for s in ("own worktree", "among its operands", "cannot be shown", "stays inside the worktree")):
        return "CC-CONTAINMENT"
    return "ERROR" if is_error else "ALLOW"


def results(path):
    uses, outs, order = {}, {}, []
    if not path.exists():
        return {}
    for line in path.read_text(errors="replace").splitlines():
        try:
            content = (json.loads(line).get("message") or {}).get("content")
        except json.JSONDecodeError:
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Bash":
                uses[block["id"]] = block.get("input", {}).get("command", "")
                order.append(block["id"])
            elif block.get("type") == "tool_result":
                body = block.get("content")
                if isinstance(body, list):
                    body = "\n".join(x.get("text", "") for x in body if isinstance(x, dict))
                outs[block.get("tool_use_id")] = (body or "", bool(block.get("is_error")))
    found = {}
    for tid in order:
        cmd = uses[tid].strip()
        for sid, pat in PATTERNS:
            if sid not in found and pat.fullmatch(cmd):
                found[sid] = classify(*outs.get(tid, ("", True)))
                break
    return found


table = {}
for cfg in configs:
    merged = {}
    for which in ("rewrite", "disabled"):
        merged.update(results(root / f"{cfg}-{which}.jsonl"))
    table[cfg] = merged

width = max(len(c) for c in ("CC-CONTAINMENT", "CC-COMPLEXITY", "PLUGIN-HOOK", "MISSING")) + 2
print(f"{'step':<5} {'command':<62}" + "".join(f"{c:<{width}}" for c in configs))
for sid, tpl in STEPS:
    cells = "".join(f"{table[c].get(sid, 'MISSING'):<{width}}" for c in configs)
    print(f"{sid:<5} {tpl[:60]:<62}{cells}")
PY
