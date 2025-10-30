# Subtitlecat Layout Watch

This directory vendors a minimal, headless build of [`Witten1997/subtitle-find`](https://github.com/Witten1997/subtitle-find)
that focuses on the subtitlecat search crawler. The original project bundles
interactive menus and a Spring Boot UI; the pared down build keeps only the
crawler logic so the repository can monitor subtitlecat's HTML structure during
continuous integration.

## Java runtime requirements

* **JDK 17 or newer** is required to compile and run the watcher.
* Maven 3.8+ is recommended for local builds (`mvn -v` should report Java 17).

The Maven build produces a `subtitlecat-layout-watch-jar-with-dependencies.jar`
file that contains all runtime dependencies (OkHttp, jsoup and SLF4J).

## Building

```bash
mvn -f tools/subtitlecat-layout-watch/pom.xml -DskipTests package
```

The command emits `tools/subtitlecat-layout-watch/target/subtitlecat-layout-watch-jar-with-dependencies.jar`.
The optional classifier-less jar (without dependencies) can be ignored.

## Running the CLI directly

```bash
java -jar tools/subtitlecat-layout-watch/target/subtitlecat-layout-watch-jar-with-dependencies.jar \
  --snapshot-dir tools/subtitlecat-layout-watch/snapshots \
  "The Matrix" "Game of Thrones S01E01"
```

The CLI prints a JSON payload summarising the attempted selectors, HTTP status
code, number of resolved rows and the top results for each search keyword. When
`--snapshot-dir` is supplied a raw HTML copy of each response is written to the
specified folder so it can be reused in parser tests.

## Python wrapper

The repository exposes a Python helper (`watch_subtitlecat.py`) that wraps the
CLI, interprets the JSON diagnostics and exits non-zero whenever the selectors
no longer produce results. See the developer documentation for details on
running the wrapper locally and updating parser fixtures from the stored
snapshots.
