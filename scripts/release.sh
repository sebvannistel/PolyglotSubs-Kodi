#!/bin/bash

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <github-token> <increment> [--no-release]" >&2
  echo "Example: $0 ghp_xxxxx patch" >&2
  exit 1
fi

token=$1
increment=$2
shift 2

create_release=true
if [[ ${1-} == "--no-release" ]]; then
  create_release=false
fi

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

if [[ -n $(git status --porcelain) ]]; then
  echo "Working tree must be clean before running the release script." >&2
  exit 1
fi

echo "Updating version and changelog with Commitizen..."
cz bump --yes --files-only --changelog --increment "$increment"

echo "Synchronizing addon.xml news entries..."
news_entry=$(python scripts/update_news.py --stdout)

version=$(cz version --project)
release_name="v$version"
tag="service.subtitles.polyglotsubs-kodi/service.subtitles.polyglotsubs-kodi-$version"

git add addon.xml CHANGELOG.md pyproject.toml .cz.toml
if git diff --cached --quiet; then
  echo "No versioning changes detected after bump; aborting." >&2
  exit 1
fi

git commit -m "release: $release_name"
if git rev-parse "$tag" >/dev/null 2>&1; then
  echo "Tag $tag already exists. Delete it or choose a different increment." >&2
  exit 1
fi
git tag "$tag"

if ! $create_release; then
  echo "Skipping GitHub release creation (flagged with --no-release)."
  exit 0
fi

if [[ -n ${GITHUB_REPOSITORY-} ]]; then
  repo_slug=$GITHUB_REPOSITORY
else
  remote_url=$(git remote get-url origin 2>/dev/null || true)
  if [[ $remote_url =~ github.com[:/]([^/]+)/([^/.]+)(\.git)?$ ]]; then
    repo_slug="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
  else
    echo "Unable to determine repository slug from git remotes." >&2
    exit 1
  fi
fi

api="https://api.github.com/repos/$repo_slug"

post_data=$(python - "$tag" "$release_name" <<'PY'
import json
import sys

tag = sys.argv[1]
name = sys.argv[2]
body = sys.stdin.read()

print(json.dumps({
    "tag_name": tag,
    "name": name,
    "body": body,
}))
PY
<<<"$news_entry")

echo "Creating GitHub release $release_name ($tag) for $repo_slug"

curl \
  --fail \
  --header "Authorization: token $token" \
  --header "Accept: application/vnd.github.v3+json" \
  --data "$post_data" \
  "$api/releases"
