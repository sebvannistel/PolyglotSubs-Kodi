# Contributing to PolyglotSubs-Kodi

First off, thank you for considering contributing to PolyglotSubs-Kodi! Your help is appreciated.
Please note that this project adheres to a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## How Can I Contribute?

### Reporting Bugs
*   Ensure the bug was not already reported by searching on GitHub under [Issues](https://github.com/sebvannistel/PolyglotSubs-Kodi/issues).
*   If you're unable to find an open issue addressing the problem, [open a new one](https://github.com/sebvannistel/PolyglotSubs-Kodi/issues/new). Be sure to include a **title and clear description**, as much relevant information as possible, and a **code sample** or an **executable test case** demonstrating the expected behavior that is not occurring.
*   Include details like your Kodi version, PolyglotSubs-Kodi addon version, and the steps you took to encounter the issue. Logs from Kodi are also very helpful.

### Suggesting Enhancements or New Features
*   Open a new issue on GitHub. Provide a clear description of the enhancement or feature you're suggesting and why it would be beneficial.

### Pull Requests
We welcome pull requests for bug fixes and improvements.

#### Setting Up Your Development Environment
1.  **Fork the repository** on GitHub.
2.  **Clone your fork** locally:
    ```bash
    git clone https://github.com/YOUR_USERNAME/PolyglotSubs-Kodi.git
    cd PolyglotSubs-Kodi
    ```
3.  **Python Environment:** This project is a Kodi addon. For development, you'll primarily be working with Python files. It's recommended to use a virtual environment for Python projects if you plan to run local linters or tools.
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows use `source .venv\Scripts\activate`
    ```
4.  **Dependencies for Linting/Testing:**
    Install development dependencies (linters, test runners):
    ```bash
    pip install -r requirements-dev.txt 
    ```
    The project uses `.flake8` for linting.

#### Running Linters and Tests

To run all linters and the test suite in one step before committing or pushing, use the preflight script:

```bash
scripts/preflight.sh
```

It executes `pre-commit run --all-files` and `pytest` to catch formatting issues and failing tests early.

*   **Install pre-commit hooks:**

*   **Pre-commit:** Run the pre-commit hooks to format and lint code:
    ```bash
    pre-commit run --all-files
    ```
    The configuration excludes bundled third-party modules in `a4kSubtitles/lib/third_party/`.
*   **Linting:** Ensure your changes pass linting before submitting:

    ```bash
    pre-commit install
    ```
*   **Linting:** Run all pre-commit checks:
    ```bash
    pre-commit run --all-files
    ```
*   **Tests:** Run the automated test suite:
    ```bash
    pytest
    ```
    The tests mock Kodi's environment and can be run from the project root after installing `requirements-dev.txt`.
    Integration tests are skipped by default. Include them with:
    ```bash
    pytest --run-integration
    ```

#### Subtitlecat layout watcher

The repository ships a minimal build of [`Witten1997/subtitle-find`](https://github.com/Witten1997/subtitle-find) so we can
catch subtitlecat.com layout regressions quickly.

* Build and run the watcher locally with:

  ```bash
  scripts/watch_subtitlecat.sh
  ```

  The helper builds the Java jar on demand (requires **JDK 17+**) and invokes
  `tools/subtitlecat-layout-watch/watch_subtitlecat.py` against a set of
  representative titles.

* The Python wrapper exits non-zero when selectors stop matching. Review the
  diagnostics printed on failure — they include attempted CSS selectors, a
  clipped HTML response, and the path to the stored DOM snapshot.

* When the watcher highlights a change, refresh the parser fixtures by copying
  the snapshots into the test suite and rerunning the targeted tests:

  ```bash
  tools/subtitlecat-layout-watch/watch_subtitlecat.py --update-test-fixtures
  pytest tests/services/test_subtitlecat_layout_watch.py
  ```

  The fixtures live under `tests/data/subtitlecat_watch/` and power
  `tests/services/test_subtitlecat_layout_watch.py`, ensuring parser changes are
  validated against the captured HTML.

#### Coding Standards
*   Please follow the existing code style.

*   Run `pre-commit run --all-files` to check for linting errors before submitting a pull request. Configuration for `flake8` is in `.flake8`.

*   Run `pre-commit run --all-files` to check for formatting and linting issues. Configuration is in `.pre-commit-config.yaml` and `.flake8`.
*   Bundled third-party code lives in `a4kSubtitles/lib/third_party/`. These files are intentionally excluded from pre-commit hooks and should not be edited or linted.

*   Ensure your code is well-commented, especially in complex or non-obvious parts.

#### Submitting Pull Requests
1.  Create a new branch for your changes:
    ```bash
    git checkout -b your-feature-branch-name
    ```
2.  Make your changes, commit them with a clear commit message.
3.  Push your branch to your fork on GitHub:
    ```bash
    git push origin your-feature-branch-name
    ```
4.  Open a pull request from your fork to the main `PolyglotSubs-Kodi` repository.
5.  Provide a clear description of the changes in your pull request. Explain the problem you're solving or the feature you're adding.

### Considering Upstream Contributions
While this is a fork with specific modifications (like Subtitlecat.com integration), if you develop a general improvement or bug fix that could benefit the original [a4kSubtitles](https://github.com/a4k-openproject/a4kSubtitles) project, please consider opening an issue or pull request there as well. Collaborative efforts benefit the entire community.

Thank you!
