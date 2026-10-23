***SYNTAX marked-en***

# Synthetic Python function example

Use only this disposable local workspace and Python's standard library. Do not
install packages, use web search or access external services. Preserve this task
list and let the controller set DONE. Report blockers instead of writing
process_stop. Do not change requirements or skip tests to obtain a passing result.

***CFG network_access=false web_search=disabled***
1. ***Task***: Create calculator.py with a side-effect-free function add(a, b) for integer inputs, and test_calculator.py using unittest. Document actual checks in todo_result_1.md.
    Acceptance: add(2, 3) returns 5, add(-2, 3) returns 1, and add(0, 0) returns 0. Include at least one discovered unittest test for each case. Importing calculator.py must perform no file, network or process operation. Handling non-integer inputs is outside this task's scope. Run unittest discovery against test_calculator.py and report the test count and result; zero tests is not success.

***CFG network_access=false web_search=disabled***
2. ***Task***: Independently inspect calculator.py and test_calculator.py against task 1's original requirements. Run the discovered tests and record the verified cases, count and result in todo_result_2.md.
    Acceptance: Verify all three required cases and the absence of import-time side effects. Document any local correction and rerun the tests after correcting it. Do not weaken tests or requirements to obtain success. This task does not replace the controller's mandatory review of either task.
