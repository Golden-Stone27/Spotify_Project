"""System Brain's pytest adapter. Part of the System Brain templates: don't edit it here (running
`/system-brain setup` again replaces it). The root `conftest.py` loads it with
`pytest_plugins = ["sb_adapter"]`.

What it does:
1. Inside a System Brain worktree (`.worktrees/<ID>` or `.claude/worktrees/<name>`), a pytest run
   that was given no paths collects only the task test folders (`<test_folder>/T<NN>-<name>/` and
   `<test_folder>/integration-<run>/`), never the project's other tests. Workers test only their
   own task; the integrator runs the full suite with explicit paths. Runs given paths, and every
   run outside a System Brain worktree, are never limited.
2. Native tests (C#, ...): each language is one runner module in `sb_langs/` next to this file.
   A task folder holding that language's files becomes one collector; the language's shared test
   project is built and run once per pytest session, and every native test becomes a pytest
   item. The no-false-pass rules live here, the same for every language: a build failure, a tool
   that doesn't start, a timeout, no results, or 0 tests for the task in a folder that has native
   test files is one failed item, never a pass. `docs/multilang-spec.md`, "Adding a language",
   describes a runner module.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

_TASK_FOLDER = re.compile(r"T\d+-[A-Za-z0-9-]+|integration-[A-Za-z0-9_-]+")
_TESTS = pytest.StashKey[Path]()
_RUNS = pytest.StashKey[dict]()
_SEEN = pytest.StashKey[set]()
_TAIL = 40   # lines of tool output shown with a failed item


def _load_languages() -> list:
    """Every runner module in `sb_langs/` (files starting with `_` are skipped)."""
    found = []
    for path in sorted((Path(__file__).resolve().parent / "sb_langs").glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"sb_lang_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        found.append(module)
    return found


LANGUAGES = _load_languages()


def _test_folder(root: Path) -> str:
    """`test_folder` from `Workflow/project.md`; `Tests` when the file or the key is missing."""
    facts = root / "Workflow" / "project.md"
    if facts.is_file():
        for line in facts.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() == "test_folder" and value.strip():
                return value.strip().strip("/")
    return "Tests"


def _in_sb_worktree(root: Path) -> bool:
    parent = root.parent
    return parent.name == ".worktrees" or (parent.name == "worktrees" and parent.parent.name == ".claude")


def _given_paths(config: pytest.Config) -> bool:
    source = getattr(config, "args_source", None)
    if source is None:   # a pytest without args_source: never limit (runs more, never less)
        return True
    return source == pytest.Config.ArgsSource.ARGS


def pytest_addoption(parser: pytest.Parser) -> None:
    for lang in LANGUAGES:
        parser.addini(f"sb_timeout_{lang.NAME}", f"System Brain: seconds per {lang.LABEL} build or test run",
                      default=str(lang.TIMEOUT))


def pytest_configure(config: pytest.Config) -> None:
    root = Path(str(config.rootpath))
    if _in_sb_worktree(root) and not _given_paths(config):
        config.stash[_TESTS] = root / _test_folder(root)


def _limited_out(path: Path, config: pytest.Config) -> bool:
    """True when a plain run in a worktree must not collect this path (outside the task folders)."""
    tests = config.stash.get(_TESTS, None)
    if tests is None:
        return False
    if path == tests or path in tests.parents:   # on the way down to the task folders
        return False
    if tests in path.parents:
        return not _TASK_FOLDER.fullmatch(path.relative_to(tests).parts[0])
    return True


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    path = Path(collection_path)
    if any(getattr(lang, "ignore_dir", None) and lang.ignore_dir(path) for lang in LANGUAGES):
        return True   # build output (bin/, obj/, ...)
    return True if _limited_out(path, config) else None


# --- running a language's tool --------------------------------------------------------------

class ToolError(Exception):
    """A run that can't give results: the reason is the failed item's name."""

    def __init__(self, reason: str, output: str = "") -> None:
        super().__init__(reason)
        self.output = output


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        pass


class RunContext:
    """What a runner gets: where things are, a fresh temp folder for this run's results, and
    `run()`, which starts a tool with the timeout and kills its whole process tree when it hits it.
    (The same helper as the wrapper's `sb_run.run_process`; a template can't import the wrapper.)"""

    def __init__(self, root: Path, tests: Path, tmp: Path, timeout: float) -> None:
        self.root, self.tests, self.tmp, self.timeout = root, tests, tmp, timeout
        self.output = ""   # everything the tools printed in this run, for a failed item's tail
        self._calls = 0

    def run(self, args: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
        exe = shutil.which(args[0])
        if exe is None:
            raise ToolError(f"{args[0]} not found")
        full_env = {**os.environ, **(env or {})}
        self._calls += 1
        out_path = self.tmp / f"out-{self._calls}.txt"
        with out_path.open("wb") as out:
            try:
                proc = subprocess.Popen([exe, *args[1:]], cwd=str(self.root), env=full_env, stdin=subprocess.DEVNULL,
                                        stdout=out, stderr=subprocess.STDOUT, start_new_session=(os.name != "nt"))
            except OSError as e:
                raise ToolError(f"{args[0]} did not start: {e}") from None
            try:
                proc.wait(timeout=self.timeout)
                timed_out = False
            except subprocess.TimeoutExpired:
                _kill_tree(proc.pid)
                proc.wait()
                timed_out = True
        text = out_path.read_bytes().decode("utf-8", errors="replace")
        self.output += f"$ {' '.join(args)}\n{text}\n"
        if timed_out:
            raise ToolError(f"timed out after {self.timeout:.0f} s", self.output)
        return proc.returncode, text


@dataclass
class _Outcome:
    error: str | None = None
    exit_code: int | None = None
    results: list[tuple[str, str, str]] = field(default_factory=list)   # (full name, outcome, message)
    output: str = ""


def _run_once(config: pytest.Config, key: tuple, lang, call) -> _Outcome:
    """One tool run per key per pytest session; every collector of that key shares it."""
    runs = config.stash.setdefault(_RUNS, {})
    if key in runs:
        return runs[key]
    root = Path(str(config.rootpath))
    timeout = float(config.getini(f"sb_timeout_{lang.NAME}") or lang.TIMEOUT)
    with tempfile.TemporaryDirectory(prefix="sb-", ignore_cleanup_errors=True) as tmp:
        ctx = RunContext(root, root / _test_folder(root), Path(tmp), timeout)
        try:
            exit_code, results = call(ctx)
            outcome = _Outcome(None, exit_code, list(results), ctx.output)
        except Exception as e:   # anything that goes wrong is a failure, never a pass
            outcome = _Outcome(str(e) or type(e).__name__, None, [], getattr(e, "output", "") or ctx.output)
    runs[key] = outcome
    return outcome


def _task_filter(config: pytest.Config, tests: Path) -> list[str] | None:
    """The task folders on pytest's command line, or None (no filter) when any path given is
    not inside a task folder (the whole suite, a plain run, a parent folder)."""
    tasks = set()
    base = Path(str(config.invocation_params.dir))
    tests = tests.resolve()
    for arg in config.args:
        path = Path(arg.split("::")[0])
        path = (path if path.is_absolute() else base / path).resolve()
        try:
            parts = path.relative_to(tests).parts
        except ValueError:
            return None
        if not parts or not _TASK_FOLDER.fullmatch(parts[0]):
            return None
        tasks.add(parts[0])
    return sorted(tasks) or None


# --- collection -------------------------------------------------------------------------------

def _task_of(path: Path, tests: Path) -> str | None:
    try:
        parts = path.relative_to(tests).parts
    except ValueError:
        return None
    return parts[0] if len(parts) > 1 and _TASK_FOLDER.fullmatch(parts[0]) else None


def pytest_collect_file(file_path: Path, parent: pytest.Collector):
    if not LANGUAGES:
        return None
    path = Path(file_path)
    root = Path(str(parent.config.rootpath))
    tests = root / _test_folder(root)
    if _limited_out(path, parent.config):
        # A test project named in testpaths (pytest doesn't ask ignore_collect for those): an empty
        # collector, so a plain run in a worktree neither runs it nor stops at "no collectors".
        if any(path.name.lower().endswith(tuple(getattr(lang, "PROJECT_SUFFIXES", ()))) for lang in LANGUAGES):
            return _Nothing.from_parent(parent, path=path)
        return None
    seen = parent.config.stash.setdefault(_SEEN, set())
    task = _task_of(path, tests)
    for lang in LANGUAGES:
        if task and path.suffix.lower() in lang.EXTENSIONS:
            if (lang.NAME, task) in seen:   # the folder's first file collects for the whole folder
                return None
            seen.add((lang.NAME, task))
            # A stable ID, whichever file collects: <test_folder>/<task>/<lang>::<full native name>
            anchor = f"{tests.relative_to(root).as_posix()}/{task}/{lang.NAME}"
            return TaskFolderTests.from_parent(parent, path=path, name=lang.NAME, nodeid=anchor, lang=lang,
                                               task=task, tests=tests)
        is_project = getattr(lang, "is_test_project", None)
        if (is_project and path != tests / lang.SHARED_PROJECT and path.name.lower().endswith(tuple(lang.PROJECT_SUFFIXES))
                and is_project(path)):
            return ProjectTests.from_parent(parent, path=path, lang=lang)
    return None


class _Nothing(pytest.File):
    def collect(self):
        return []


class NativeFailure(Exception):
    pass


class NativeItem(pytest.Item):
    def __init__(self, *, outcome: str, message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.outcome, self.message = outcome, message

    def runtest(self) -> None:
        if self.outcome == "passed":
            return
        if self.outcome == "skipped":   # a skip is not a pass
            pytest.skip(self.message.splitlines()[0] if self.message else "not run")
        raise NativeFailure(self.message or self.outcome)

    def repr_failure(self, excinfo, style=None):
        if isinstance(excinfo.value, NativeFailure):
            return str(excinfo.value)
        return super().repr_failure(excinfo, style)

    def reportinfo(self):
        return self.path, None, self.name


def _tail(text: str) -> str:
    lines = [l for l in text.splitlines() if l.strip()]
    return "\n".join(lines[-_TAIL:])


class _NativeFile(pytest.File):
    def _error(self, reason: str, output: str):
        first = reason.splitlines()[0] if reason else "failed"
        message = reason + (f"\n--- {self.lang.LABEL} output (tail) ---\n{_tail(output)}" if output.strip() else "")
        return NativeItem.from_parent(self, name=f"{self.lang.NAME}: {first}", outcome="failed", message=message)

    def _items(self, outcome: _Outcome, results: list, missing: str):
        if outcome.error:
            yield self._error(outcome.error, outcome.output)
            return
        if not results:
            yield self._error(missing, outcome.output)
            return
        if outcome.exit_code and not any(r[1] not in ("passed", "skipped") for r in outcome.results):
            yield self._error(f"{self.lang.TOOL} exited {outcome.exit_code}", outcome.output)
        used: dict[str, int] = {}
        for name, result, message in results:
            used[name] = used.get(name, 0) + 1
            item_name = name if used[name] == 1 else f"{name} [{used[name]}]"
            yield NativeItem.from_parent(self, name=item_name, message=message,
                                         outcome=result if result in ("passed", "skipped") else "failed")


class TaskFolderTests(_NativeFile):
    """One language's tests of one task folder. Its ID is the folder plus the language, not the
    file that happened to collect, so a new file never renames the folder's tests."""

    def __init__(self, *, lang, task: str, tests: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.lang, self.task, self.tests = lang, task, tests

    def collect(self):
        names = _task_filter(self.config, self.tests)
        native_names = [self.lang.native_name(t) for t in names] if names else None
        outcome = _run_once(self.config, (self.lang.NAME, "tasks"), self.lang,
                            lambda ctx: self.lang.run_tasks(ctx, native_names))
        native = self.lang.native_name(self.task)
        mine = [r for r in outcome.results if r[0].startswith(native + ".")]
        yield from self._items(outcome, mine, f"no tests in {self.lang.KIND} {native}")


class ProjectTests(_NativeFile):
    """An existing native test project of the project's own (the full suite)."""

    def __init__(self, *, lang, **kwargs) -> None:
        super().__init__(**kwargs)
        self.lang = lang

    def collect(self):
        path = Path(self.path)
        outcome = _run_once(self.config, (self.lang.NAME, str(path)), self.lang,
                            lambda ctx: self.lang.run_project(ctx, path))
        yield from self._items(outcome, outcome.results, f"no tests in {path.name}")
