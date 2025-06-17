# Running Python unit/integration tests/smoke tests

Note: you can run pytest test cases in parallel with command -n auto.

To run a specifc unit test

    pytest -v PathToPythonTestFile::TestClassName::TestMethodName
    pytest -v ./tests/neuro-san/internals/graph/test_sly_data_redactor.py::TestSlyDataRedactor::test_assumptions

To run all unit tests
    
    Note: you will need to start server service 1st as the test case "music_nerd_pro" [HTTP] is part of unit test.
    run: build_scripts/server_start.sh

    pytest -v ./tests

To debug a specific unit test, import pytest in the test source file

    import pytest

Set a trace to stop the debugger on the next line

    pytest.set_trace()

Run pytest with '--pdb' flag

    pytest -v --pdb ./tests/neuro-san/internals/graph/test_sly_data_redactor.py

To run all integration tests

    pytest -v ./tests -m "integration"

To run all smoke tests
    
    Note: you must start the server service first, as the test cases require it most.
    run: build_scripts/server_start.sh
    
    pytest -s --verbose -m "smoke"