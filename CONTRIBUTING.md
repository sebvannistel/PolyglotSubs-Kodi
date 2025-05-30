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
*   **Linting:** Ensure your changes pass linting before submitting:
    ```bash
    flake8 .
    ```
*   **Tests:** The repository may contain a `tests/` directory.
    *   (Placeholder: Add specific instructions here if you have a test suite, e.g., `pytest`)
    *   For Kodi addon development, testing can sometimes involve mocking Kodi's environment or running within a Kodi development setup. Please describe any specific test procedures if applicable.

#### Coding Standards
*   Please follow the existing code style.
*   Run `flake8` to check for linting errors before submitting a pull request. Configuration is in `.flake8`.
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