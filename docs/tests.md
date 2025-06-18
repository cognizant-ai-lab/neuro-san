# Running Python unit/integration tests/smoke tests

## Running a single test

To run a specifc unit test

    pytest -v PathToPythonTestFile::TestClassName::TestMethodName
    pytest -v ./tests/neuro_san/internals/graph/test_sly_data_redactor.py::TestSlyDataRedactor::test_assumptions

## Different kinds of tests

Neuro SAN has different kinds of tests marked with @pytest.mark.<some_marker>.
The markers we use come in a few different flavors for different purposes.

### Pre-requisites

Many (but not absolutely all) tests will require an active OPENAI_API_KEY or other equivalent key
from another LLM provider in order to run successfully.  Please be sure you have a basic
agent network running in your environment as described in the top-level README.md to this repo.

### Basic unit tests

Unit tests are run in this repo with every push to every branch.
Because they are the norm, they actually have no marker, and in order to run
the basic suite of unit tests, you actually need to specify that you do not
want to run other kinds of tests (described later).

To run all basic unit tests:

    pytest -v -m "not integration and not smoke and not needs_server" -n auto

The -n auto allows the tests to run in parallel on available CPUs.

### needs_server

Some unit tests are marked as "@pytest.mark.needs_server"
In order to run these, you will need to start a neuro-san server first:

    build_scripts/server_start.sh

To run all unit tests, including the ones that need a server

    pytest -v -m "not integration and not smoke" -n auto

### integration tests

Some unit tests are marked as "@pytest.mark.integration"
These tests usually take a larger than normal amount of time to complete
and are not run with every checkin, but only once a night.

    pytest -v -m "integration" -n auto

### smoke tests

Some unit tests are marked as "@pytest.mark.smoke"
These tests often have some kind of extended setup associated with them,
whether it's a server running, extra LLM provider keys, or extra environment
variables set.  They also often take larger than normal amount of time to complete
and are not run with every checkin, but at least once with every release.

You will need to have a server running in order for smoke tests to succeed:

    build_scripts/server_start.sh

... then:

    pytest -v -m "smoke" -n auto

### Debugging

To debug a specific unit test, import pytest in the test source file

    import pytest

Set a trace to stop the debugger on the next line

    pytest.set_trace()

Run pytest with '--pdb' flag

    pytest -v --pdb ./tests/neuro_san/internals/graph/test_sly_data_redactor.py
