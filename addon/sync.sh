#!/bin/sh
# Copy the add-on files into the add-on repository and show what changed.
#
# Home Assistant needs repository.yaml at a repo root, so the add-on lives in
# its own repository while its source lives here. Copying by hand has already
# produced one version mismatch, and a stale copy is the same class of problem
# as the stale bundle files that cost an evening earlier in this project.
#
#   addon/sync.sh [path-to-addon-repo]     default: ../pi-panel-addon
set -eu

SRC=$(cd "$(dirname "$0")" && pwd)
DEST=${1:-$(cd "$SRC/.." && pwd)/../pi-panel-addon}

if [ ! -d "$DEST/.git" ]; then
  echo "No git repository at $DEST" >&2
  echo "Pass the path as an argument, or see addon/README.md to create it." >&2
  exit 1
fi

# sync.sh itself is a tool for this repo, not part of the add-on.
for f in repository.yaml panel-server README.md; do
  cp -r "$SRC/$f" "$DEST/"
done

VERSION=$(grep '^version:' "$DEST/panel-server/config.yaml" | cut -d'"' -f2)
echo "Synced version $VERSION to $DEST"
echo

if git -C "$DEST" diff --quiet && git -C "$DEST" diff --cached --quiet; then
  echo "No changes — the add-on repo already matches."
  exit 0
fi

git -C "$DEST" --no-pager diff --stat
echo
echo "Next:"
echo "  git -C \"$DEST\" add -A"
echo "  git -C \"$DEST\" commit -m \"Panel Config Server $VERSION\""
echo "  git -C \"$DEST\" push"
echo
echo "Tag the main repo v$VERSION first, so the image exists before Home"
echo "Assistant is told to look for it."
