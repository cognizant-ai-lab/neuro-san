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

Some unit tests (for example, the S3 reservations storage suite under
`tests/neuro_san/service/watcher/temp_networks/`) are fully mocked and run without any
LLM, AWS, or external service keys.

### Basic unit tests

Unit tests are run in this repo with every push to every branch.
Because they are the norm, they actually have no marker, and in order to run
the basic suite of unit tests, you actually need to specify that you do not
want to run other kinds of tests (described later).

To run all basic unit tests:

    pytest -v -m "not integration and not smoke and not needs_server" -n auto

The -n auto allows the tests to run in parallel on available CPUs.

### Mock-based unit tests for cloud-backed storage

Some unit tests exercise components that talk to AWS or other cloud
services in production but use an in-memory mock of the SDK client
in tests.  These tests do not need any AWS credentials, do not pull
in `moto` or `localstack`, and run anywhere a basic Python
environment is available.

The first such suite covers `S3ReservationsStorage`:

    pytest --verbose tests/neuro_san/service/watcher/temp_networks/

Layout:

- `_test_base.py` — `FakeS3Client` (in-memory stand-in for boto3 S3
  client) and `S3ReservationsStorageTestBase` (shared scaffolding,
  patches `boto3_client` to inject the fake).
- `conftest.py` — scoped override of the `OPENAI_API_KEY` autouse
  fixture for this subtree only.
- `test_*.py` — one file per scenario (round-trip, retries, batch
  semantics, custom prefix, etc.). One test per file keeps failure
  diagnostics clean.

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

Required environment variables:

    export PYTHONPATH=$(pwd)
    export AGENT_TOOL_PATH="./neuro_san/coded_tools"
    export AGENT_MANIFEST_FILE="./neuro_san/registries/manifest.hocon"

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

Required environment variables:

    export PYTHONPATH=$(pwd)
    export AGENT_TOOL_PATH="./neuro_san/coded_tools"
    export AGENT_MANIFEST_FILE="./neuro_san/registries/manifest.hocon"

### Adding a new data-driven test case

Data-driven tests use HOCON fixture files to define test cases declaratively.
See [test_case_hocon_reference.md](test_case_hocon_reference.md) for the full HOCON schema.

To add a new test case:

1. Create a fixture HOCON file under `tests/fixtures/<agent_name>/your_test.hocon`

2. Register the HOCON file in the appropriate test class under
   `tests/neuro_san/zzz_hocons/` by adding it to the list inside
   `@parameterized.expand()`:

   - For integration tests: `test_integration_test_hocons.py`
   - For smoke tests: `test_smoke_test_hocons.py`

   Example:

        @parameterized.expand(DynamicHoconUnitTests.from_hocon_list([
            "my_agent/my_new_test.hocon",
        ]), skip_on_empty=True)

3. Run the test (integration example):

        export PYTHONPATH=$(pwd)
        export AGENT_TOOL_PATH="./neuro_san/coded_tools"
        export AGENT_MANIFEST_FILE="./neuro_san/registries/manifest.hocon"
        pytest -s --verbose -m "integration" -k "my_agent_my_new_test" --timer-top-n 100

   The `-k` filter name is derived from the HOCON path: slashes become `_`
   and `.hocon` is stripped.

### Debugging

To debug a specific unit test, import pytest in the test source file

    import pytest

Set a trace to stop the debugger on the next line

    pytest.set_trace()

Run pytest with '--pdb' flag

    pytest -v --pdb ./tests/neuro_san/internals/graph/test_sly_data_redactor.py

## Note on Markdown Linting

We use [pymarkdown](https://pymarkdown.readthedocs.io/en/latest/) to run linting on .md files.
`pymarkdown` can be configured via `.pymarkdown.yaml` located in the projects top level folder. See
this [page](https://pymarkdown.readthedocs.io/en/latest/rules/) for all the configuration options.
`pymarkdown` is installed in the virtual environment as part of the build dependency requirements
specified in `build-requirements.txt`.

To run an installed version of `pymarkdown`, run the following command:

    pymarkdown --config ./.pymarkdownlint.yaml scan ./docs ./README.md

The `--config` flag is used to pass in a configuration file to `pymarkdownlint`

To see all the options, run the following command:

    pymarkdown --help
