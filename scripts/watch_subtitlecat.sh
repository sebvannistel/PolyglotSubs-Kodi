#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JAR_PATH="$REPO_ROOT/tools/subtitlecat-layout-watch/target/subtitlecat-layout-watch-jar-with-dependencies.jar"

if [ ! -f "$JAR_PATH" ]; then
  mvn -f "$REPO_ROOT/tools/subtitlecat-layout-watch/pom.xml" -DskipTests package
fi

python "$REPO_ROOT/tools/subtitlecat-layout-watch/watch_subtitlecat.py" "$@"
