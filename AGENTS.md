<!-- system-brain:start -->
# AGENTS.md: worker rulebook

Standing rules for every worker (Codex, Gemini, Claude) and the integrator. Your task is in
your brief, never here.

## Rules you must never break
1. **ONLY change the files listed under "Allowed files" in your brief, plus your own tests in
   the test folder named in your brief header (`<test folder>/<task ID>/`). Nothing else.**
2. **Never weaken or delete an existing test to make it pass.** Ask with `needs_input` instead.
3. **If a test looks wrong, or the task can't be done within the allowed files, do NOT work
   around it.** Stop and write `request: needs_input: <your question>` in your report. Asking is
   always the correct move.
4. **Write tests for your changes and run them with the test command in your brief. Never claim
   tests pass unless you ran that command and saw them pass.**
5. **In your report, list the tests you wrote (`tests:`) and the exact command you ran
   (`command:`).**

## Where you work
- Work only in the working directory named in your brief header.
- Write your notes only to `.sb/progress.md` and `.sb/result.md` in that directory.
- If the header says `First: run git merge --no-edit task/<ID>`, do that before anything else.
- If the brief points to a previous `progress.md`, read it first and continue from its `Next:` line.

## Tests
- Put your tests in the test folder named in your brief header (`<test folder>/<task ID>/`).
- Run them with the exact test command from your brief header. In your worktree it runs only the
  task test folders, not the project's other tests.
- If a test outside your test folder fails and your task didn't cause it, don't fix it; mention
  it under `## Problems` in your report.
- Test in the language of the code you change: changed `.py` code needs a `test_*.py`, changed
  C++ code (`.cpp`, `.h`, ...) a `.cpp` test, C# a `.cs` test, Java a `.java` test, in your test
  folder. Otherwise the check fails your task even if every test passes. Tests check behaviour:
  call the code; never read source files as text.

## Tests in other languages
Your test folder may hold Python and native tests side by side. The test command in your brief
builds and runs all of them.
- C#: NUnit, namespace = the "Native test name" in your brief header (e.g. `T01_login`).
- C++: each `.cpp` file directly in your test folder is one test program with its own `main()`;
  ctest runs it as `<Native test name>.<file name>` (e.g. `T01_login.parse_tests`) and its exit
  code decides. Use `#include "sb_check.h"` (`SB_TEST`, `SB_CHECK`, `SB_CHECK_EQ`; it supplies
  `main()`), or QtTest in a Qt project. Put helpers in headers. Never add your tests to the
  project's own `CMakeLists.txt`, and never change `sb_tests.cmake` or `sb_check.h`.
- Java: JUnit 5, package = the "Native test name" in your brief header (e.g. `t01_login`); the
  shared test build is `build.gradle` + `settings.gradle` in the test folder (the rule below
  covers them too). Write `.java` files as UTF-8 without a BOM: `javac` rejects the BOM.
Never change `sb_adapter.py`, `sb_langs/`, `conftest.py` or the shared test project
(`Tests.csproj` in the test folder) unless your brief lists them under Allowed files.

## If you are Gemini
- The only shell command you may run is `python -m pytest -q`. Any other command ends your run.
- List, read and write files with your file tools, never with shell commands.

## Progress notes: `.sb/progress.md`
Append one line per step as you go; never rewrite earlier lines. End with a single `Next:` line.
No test output here.
```
[done] step 1: created User model (src/models/user.py)
[wip]  step 2: password hashing
Next: finish hash check in auth.py, then add tests in tests/T01-login
```

## Report: `.sb/result.md`
Write one report when you stop, done or not. The key lines come first:
```
summary: <one line>
next: <one line, or "-">
request: none | needs_input: <question>
tests: tests/T01-login/test_login.py, tests/T01-login/test_hash.py
command: python -m pytest -q
## Changes
## Decisions
## Problems
```
<!-- system-brain:end -->
