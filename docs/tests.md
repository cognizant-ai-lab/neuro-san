# Running Python unit/integration tests/smoke tests

To run a specifc unit test

    pytest -v PathToPythonTestFile::TestClassName::TestMethodName
    pytest -v ./tests/neuro-san/internals/graph/test_sly_data_redactor.py::TestSlyDataRedactor::test_assumptions

To run all unit tests
    
    You will need to start server service 1st as the test case "music_nerd_pro" [HTTP] is part of unit test.
    build_scripts/server_start.sh

    pytest -v ./tests

    You can run pytest test cases in parallel with command -n auto.
    pytest -v ./tests -n auto

To debug a specific unit test, import pytest in the test source file

    import pytest

Set a trace to stop the debugger on the next line

    pytest.set_trace()

Run pytest with '--pdb' flag

    pytest -v --pdb ./tests/neuro-san/internals/graph/test_sly_data_redactor.py

To run all integration tests

    pytest -v ./tests -m "integration"

    You can run pytest test cases in parallel with command -n auto.
    pytest -v ./tests -m "integration" -n auto

To run all smoke tests
    
    You must start the server service first, as the test cases require it most.
    build_scripts/server_start.sh
    
    pytest -s --verbose -m "smoke"

    You can run pytest test cases in parallel with command -n auto.
    pytest -s --verbose -m "smoke" -n auto