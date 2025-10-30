# Subtitlecat Layout Watcher

This directory vendors a minimal, CLI-only build of
[`Witten1997/subtitle-find`](https://github.com/Witten1997/subtitle-find) at
commit `072fa26d87ef4e5b5b94bed980359f22c7b0d597`. The upstream project ships a
Spring Boot experience; only the crawling and parsing primitives needed to
verify layout stability are included here, along with a small Java CLI wrapper
and Python automation glue.

## Runtime requirements

* **Java 17** (Temurin or equivalent). The CI workflow installs Java via
  `actions/setup-java@v4` and runs the watcher against representative titles.
* **Maven** (3.8+) to compile the vendored sources into a runnable fat jar. The
  `watch_subtitlecat.py` helper will trigger `mvn -q -DskipTests package` when a
  jar is missing.
* Python 3.10+ (already required by the repository) for the orchestration script
  and optional CLI wrapper in `scripts/watch_subtitlecat.sh`.

## Directory layout

```
subtitle-find/            # Vendored Java sources and Maven build file
watch_subtitlecat.py      # Python wrapper that builds/runs the watcher
watch_targets.json        # Representative queries and selector expectations
snapshots/                # Local-only HTML snapshots captured on failures (.gitignored)
```

The Java CLI (`com.subtitlefind.cli.LayoutWatchCli`) prints structured JSON to
stdout describing search/download selector matches, HTTP status codes, and a
base64 snapshot of the DOM that was parsed. The Python wrapper interprets that
output, enforces expectations, and mirrors failing snapshots into
`tests/services/subtitlecat/watch_snapshots/` so that parser tests can be updated
quickly.

## Usage

```bash
# Run from repository root
scripts/watch_subtitlecat.sh

# Rebuild the Java jar from scratch
scripts/watch_subtitlecat.sh --rebuild

# Skip the build step if you have already run Maven
scripts/watch_subtitlecat.sh --skip-build
```

On failure the script will:

1. Emit diagnostics that explain which selector or expectation broke.
2. Save HTML snapshots under both `tools/subtitlecat-layout-watch/snapshots/`
   (for quick inspection) and `tests/services/subtitlecat/watch_snapshots/`
   (for parser regression tests).
3. Exit with a non-zero status so CI fails loudly.

To update the parser after a layout change, run the watcher locally, commit the
captured snapshot(s) in `tests/services/subtitlecat/watch_snapshots/`, adjust the
parser to satisfy the new DOM, and ensure `pytest` passes.

## CI integration

The GitHub Actions workflow defines a dedicated job that executes
`tools/subtitlecat-layout-watch/watch_subtitlecat.py` against the queries in
`watch_targets.json`. Any selector drift (or unexpected HTTP/status failures)
causes the job to fail with actionable output and saved snapshots.
