#!/usr/bin/env bash
# setup-token.sh: create the token spike containers use and save it to ~/.config/cgpipe/env (mode 600).
# Run it in your own terminal on VM 1 (not through a `!` command in a Claude session):
#   bash pipeline/setup-token.sh            # --force replaces an existing token
# The pasted token is not echoed, not kept in shell history and not stored in this folder.
set -euo pipefail
ENVF="$HOME/.config/cgpipe/env"
CLAUDE="$HOME/.local/bin/claude"
IMAGE="cgpipe-spike:1"

if [ -s "$ENVF" ] && [ "${1:-}" != "--force" ]; then
  echo "$ENVF already exists. To replace it: bash pipeline/setup-token.sh --force"
  exit 0
fi

echo "Step 1 of 3: Claude Code shows a link. Open it, approve, and the terminal prints a token."
"$CLAUDE" setup-token
echo
read -rsp "Step 2 of 3: paste the token here (it stays hidden) and press Enter: " TOKEN
echo
if [[ ! "$TOKEN" =~ ^sk-ant-[A-Za-z0-9_-]{60,200}$ ]] || [ "$(grep -o 'sk-ant-' <<<"$TOKEN" | wc -l)" != 1 ]; then
  echo "That doesn't look like one token: paste a single token (it starts with sk-ant- and is about 100 characters)."
  echo "Nothing was saved; run the script again."
  exit 1
fi
umask 077
mkdir -p "$(dirname "$ENVF")"
printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$TOKEN" > "$ENVF"
unset TOKEN
chmod 600 "$ENVF"
echo "Saved $ENVF (mode $(stat -c %a "$ENVF"))."

echo "Step 3 of 3: checking the token inside the spike container (a one-word reply, under a cent)..."
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "The image $IMAGE isn't built yet, so the check is skipped. Build it (README section 5, step 3), then run this script again with --force."
  exit 0
fi
reply=$(docker run --rm --env-file "$ENVF" "$IMAGE" claude -p "Reply with the single word ok" --max-turns 1 2>&1 | tail -n 3) || true
if grep -qi '\bok\b' <<<"$reply"; then
  echo "The token works. The pipeline is ready: python3 -I pipeline/cgpipe.py warmup, then run."
else
  echo "The check failed. Claude said: $reply"
  echo "Run the script again with --force to create a new token."
  exit 1
fi
