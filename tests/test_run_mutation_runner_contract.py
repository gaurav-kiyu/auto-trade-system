from scripts.run_mutation_tests import _classify_pytest_result


def test_zero_returncode_is_survived():
    assert _classify_pytest_result(0, "5 passed", "") == "SURVIVED"


def test_normal_test_failure_is_killed():
    output = "FAILED tests/test_example.py::test_rule - AssertionError"
    assert _classify_pytest_result(1, output, "") == "KILLED"


def test_collection_failure_is_error():
    output = "ERROR collecting tests/test_example.py"
    assert _classify_pytest_result(2, output, "") == "ERROR"


def test_import_failure_is_error():
    output = "ImportError: cannot import name 'foo'"
    assert _classify_pytest_result(1, output, "") == "ERROR"


def test_module_not_found_is_error():
    output = "ModuleNotFoundError: No module named 'foo'"
    assert _classify_pytest_result(1, "", output) == "ERROR"


def test_syntax_failure_is_error():
    output = "SyntaxError: invalid syntax"
    assert _classify_pytest_result(1, output, "") == "ERROR"


def test_pytest_invocation_failure_is_error():
    output = "ERROR: file or directory not found: tests/missing.py"
    assert _classify_pytest_result(4, output, "") == "ERROR"


def test_no_tests_ran_is_error():
    output = "no tests ran in 0.01s"
    assert _classify_pytest_result(5, output, "") == "ERROR"
