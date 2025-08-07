import textwrap
from pathlib import Path

import pytest

pytest_plugins = ("pytester",)


def test_integration_marker_respected(pytester):
    # copy project conftest to pytester directory to include --run-integration flag
    conftest_path = Path(__file__).with_name("conftest.py")
    pytester.makeconftest(conftest_path.read_text())

    # register the integration marker to avoid warnings
    pytester.makeini(
        textwrap.dedent(
            """
            [pytest]
            markers =
                integration: mark tests that require external services and are skipped unless --run-integration is given
            """
        )
    )

    # create a sample test marked as integration
    pytester.makepyfile(
        textwrap.dedent(
            """
            import pytest

            @pytest.mark.integration
            def test_example():
                assert True
            """
        )
    )

    # By default, integration tests are skipped
    result = pytester.runpytest()
    result.assert_outcomes(skipped=1)

    # With --run-integration, the test is executed and passes
    result = pytester.runpytest("--run-integration")
    result.assert_outcomes(passed=1)
