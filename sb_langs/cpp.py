"""System Brain's C++ runner (CMake + ctest, JUnit results from `ctest --output-junit`). Part of the
System Brain templates: don't edit it here (running `/system-brain setup` again replaces it).

The adapter (`sb_adapter.py`) uses the "run" part; `sb_setup.py --lang cpp` the "setup" part.
Stdlib only, and no pytest: setup imports this file with a plain Python. The interface every
runner module has is in `docs/multilang-spec.md`, "Adding a language".

How a task's C++ tests run: every `<test folder>/<task ID>/*.cpp` is one test program (its own
`main()`), registered with ctest as `<native name>.<file stem>` (`T01_login.parse_tests`) by the
shared `<test folder>/sb_tests.cmake`. That file is pulled into the project's own CMake build
(configured into `.sb-build/` at the root) after the project's top-level `CMakeLists.txt` has
run, so the tests link the project's own library targets. The project's own build files are not
changed. Only the targets of the tasks being tested are built.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import types
import xml.etree.ElementTree as ET
from pathlib import Path

NAME = "cpp"                      # --lang cpp, sb_timeout_cpp, failed items "cpp: <reason>"
LABEL = "C++"
KIND = "C++ test group"           # "Native test name: T01_login (C++ test group)"
EXTENSIONS = (".cpp",)            # files in a task folder that make it a C++ folder
SOURCE_EXTENSIONS = (".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx")   # changed code that needs a C++ test
SHARED_PROJECT = "sb_tests.cmake"  # <test_folder>/sb_tests.cmake, the shared test build
PROJECT_SUFFIXES = ("cmakelists.txt",)   # the root CMakeLists.txt: the project's own ctest tests
TOOL = "ctest"
TIMEOUT = 1800                    # seconds per configure, build or ctest run (sb_timeout_cpp)
BUILD_DIR = ".sb-build"           # the build folder, at the project (or worktree) root
GITIGNORE = (f"{BUILD_DIR}/",)
LABEL_TASK = "sb_task"            # the ctest label of every task test
FACTS = "Workflow/project.md"     # where setup writes the toolchain (cpp_* lines)
HELPER = "sb_check.h"             # the tiny test helper next to the shared build file
MIN_CMAKE = (3, 21)               # ctest --output-junit

_TASK_FOLDER = re.compile(r"T\d+-[A-Za-z0-9-]+|integration-[A-Za-z0-9_-]+")
_ERROR_LINE = re.compile(r"\berror\b|undefined reference|multiple definition", re.I)
_LIBS_LINE = re.compile(r"^set\(SB_TEST_LIBS\b([^)]*)\)", re.M)
_MESSAGE_LINES = 60


class Failed(Exception):
    def __init__(self, reason: str, output: str = "") -> None:
        super().__init__(reason)
        self.output = output


# --- the toolchain, as setup wrote it into Workflow/project.md --------------------------------

def read_tools(root: Path) -> dict:
    """`cpp_cmake`, `cpp_generator`, `cpp_path` (repeated) and `cpp_define` (repeated, NAME=VALUE)
    from `Workflow/project.md`. Without them: `cmake` from PATH and CMake's own defaults."""
    tools = {"cmake": "cmake", "generator": None, "path": [], "define": []}
    facts = root / FACTS
    if facts.is_file():
        for line in facts.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if not sep or not value:
                continue
            if key == "cpp_cmake":
                tools["cmake"] = value
            elif key == "cpp_generator":
                tools["generator"] = value
            elif key == "cpp_path":
                tools["path"].append(value)
            elif key == "cpp_define" and "=" in value:
                tools["define"].append(value)
    return tools


def tools_lines(tools: dict) -> list[str]:
    lines = [f"cpp_cmake: {tools['cmake']}"]
    if tools.get("generator"):
        lines.append(f"cpp_generator: {tools['generator']}")
    lines += [f"cpp_path: {p}" for p in tools.get("path", [])]
    lines += [f"cpp_define: {d}" for d in tools.get("define", [])]
    return lines


def _ctest(cmake: str) -> str:
    if cmake == "cmake":
        return "ctest"
    path = Path(cmake)
    return str(path.with_name("ctest" + path.suffix))


def _env(tools: dict) -> dict[str, str]:
    """The toolchain's folders first on PATH: the compiler and its runtime DLLs, Qt's DLLs."""
    if not tools["path"]:
        return {}
    return {"PATH": os.pathsep.join([str(Path(p)) for p in tools["path"]] + [os.environ.get("PATH", "")])}


def _config(tools: dict) -> str:
    for d in tools["define"]:
        name, _, value = d.partition("=")
        if name.split(":")[0] == "CMAKE_BUILD_TYPE" and value:
            return value
    return "Debug"


# --- run (used by the adapter) ----------------------------------------------------------------

def native_name(task_id: str) -> str:
    """`T01-login` -> `T01_login`, the prefix of a task's ctest names (`T01_login.<file stem>`)."""
    return task_id.replace("-", "_")


def ignore_dir(path: Path) -> bool:
    """The build folder: nothing for pytest to walk."""
    return path.name == BUILD_DIR and path.is_dir()


def is_test_project(path: Path) -> bool:
    """The project's top-level CMakeLists.txt (next to `.git`): its ctest tests, all of them."""
    return path.name == "CMakeLists.txt" and (path.parent / ".git").exists()


def _configure(ctx, tools: dict, source: Path) -> Path:
    if not (source / "CMakeLists.txt").is_file():
        raise Failed("no CMakeLists.txt at the project root; C++ tests build inside the project's CMake build")
    build = source / BUILD_DIR
    build.mkdir(exist_ok=True)
    args = [tools["cmake"], "-S", str(source), "-B", str(build)]
    if tools["generator"]:
        args += ["-G", tools["generator"]]
    args += [f"-D{d}" for d in tools["define"]]
    shared = ctx.tests / SHARED_PROJECT
    if shared.is_file():
        hook = build / "sb_hook.cmake"
        hook.write_text(
            "# System Brain: after the project's top-level CMakeLists.txt, add the task tests.\n"
            "get_property(_sb_done GLOBAL PROPERTY SB_TASK_TESTS)\n"
            "if(NOT _sb_done)\n"
            "  set_property(GLOBAL PROPERTY SB_TASK_TESTS ON)\n"
            "  enable_testing()\n"
            f'  cmake_language(DEFER CALL include "{shared.resolve().as_posix()}")\n'
            "endif()\n", encoding="utf-8")
        args.append(f"-DCMAKE_PROJECT_INCLUDE={hook.as_posix()}")
    code, out = ctx.run(args, env=_env(tools))
    if code != 0:
        raise Failed("configure failed", out)
    return build


def _build(ctx, tools: dict, build: Path, targets: list[str] | None) -> None:
    args = [tools["cmake"], "--build", str(build), "--config", _config(tools)]
    if targets:
        args += ["--target", *targets]
    code, out = ctx.run(args, env=_env(tools))
    if code != 0:
        errors = list(dict.fromkeys(l.strip() for l in out.splitlines() if _ERROR_LINE.search(l)))
        raise Failed("build failed", "\n".join(errors) or out)


def _run_ctest(ctx, tools: dict, build: Path, selection: list[str]) -> tuple[int, list[tuple[str, str, str]]]:
    junit = ctx.tmp / "results.xml"
    args = [_ctest(tools["cmake"]), "--test-dir", str(build), "-C", _config(tools), *selection,
            "--output-junit", str(junit)]
    code, out = ctx.run(args, env=_env(tools))
    if not junit.is_file():
        raise Failed("no results file", out)
    return code, parse_junit(junit)


def run_tasks(ctx, names: list[str] | None) -> tuple[int, list[tuple[str, str, str]]]:
    """Configure the project with the task tests added, build the tests of the given tasks (None:
    every task's), run them with ctest. The adapter checks the exact name match again."""
    shared = ctx.tests / SHARED_PROJECT
    if not shared.is_file():
        rel = shared.relative_to(ctx.root).as_posix()
        raise Failed(f"{rel} missing; run setup with --lang cpp")
    tools = read_tools(ctx.root)
    with_code = {native_name(d.name) for d in ctx.tests.iterdir()
                 if d.is_dir() and _TASK_FOLDER.fullmatch(d.name) and any(d.glob("*.cpp"))}
    if names:
        names = [n for n in names if n in with_code]
        if not names:
            return 0, []
    build = _configure(ctx, tools, ctx.root)
    _build(ctx, tools, build, [f"sb_{n}" for n in names] if names else ["sb_tests"])
    selection = ["-L", f"^{LABEL_TASK}$"]
    if names:
        selection += ["-R", "^(" + "|".join(names) + r")\."]
    return _run_ctest(ctx, tools, build, selection)


def run_project(ctx, project: Path) -> tuple[int, list[tuple[str, str, str]]]:
    """The project's own ctest tests (everything but the task tests): a full build, then ctest."""
    tools = read_tools(ctx.root)
    build = _configure(ctx, tools, project.parent)
    _build(ctx, tools, build, None)
    return _run_ctest(ctx, tools, build, ["-LE", f"^{LABEL_TASK}$"])


def parse_junit(path: Path) -> list[tuple[str, str, str]]:
    """(ctest name, passed | failed | skipped, message) per `<testcase>` of ctest's JUnit file. A
    test ctest didn't run counts as skipped only when it was disabled or skipped on purpose
    (SKIP_RETURN_CODE, SKIP_REGULAR_EXPRESSION); anything else (a missing executable, ...) fails."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as e:
        raise Failed(f"no results file (unreadable: {e})") from None
    results = []
    for case in root.iter("testcase"):
        status = case.get("status", "")
        failure, skipped = case.find("failure"), case.find("skipped")
        out = (case.findtext("system-out") or "").strip()
        out = "\n".join(out.splitlines()[-_MESSAGE_LINES:])
        note = (failure if failure is not None else skipped)
        note = note.get("message", "") if note is not None else ""
        if status == "run" and failure is None:
            outcome = "passed"
        elif status == "disabled" or (status == "notrun" and note.startswith("SKIP_")):
            outcome = "skipped"
        else:
            outcome = "failed"
        message = "\n".join(t for t in (note if outcome != "passed" else "", out if outcome == "failed" else "") if t)
        results.append((case.get("name", ""), outcome, message))
    return results


# --- setup (used by sb_setup.py --lang cpp) ---------------------------------------------------

_SKIP = {"node_modules", "Workflow", BUILD_DIR}
# Known install places, after PATH and an existing build folder's CMakeCache.txt.
KNOWN_CMAKE = ["C:/Qt/Tools/CMake_64/bin/cmake.exe", "C:/Program Files/CMake/bin/cmake.exe"]
KNOWN_NINJA = ["C:/Qt/Tools/Ninja/ninja.exe"]
KNOWN_CXX = "C:/Qt/Tools/mingw*_64/bin/g++.exe"   # glob; the newest wins
KNOWN_QT = "C:/Qt/6.*/mingw_64"                  # glob, for a project that uses Qt with Qt's MinGW


def _walk(project: Path):
    """(folder, file names) of the project's own folders: no hidden ones, no build folders."""
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in _SKIP
                             and not (Path(dirpath, d) / "CMakeCache.txt").is_file())
        yield Path(dirpath), filenames


def _cmake_files(project: Path) -> list[Path]:
    return [here / f for here, files in _walk(project) for f in sorted(files)
            if f == "CMakeLists.txt" or f.endswith(".cmake") and f != SHARED_PROJECT]


def _read_cache(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"([A-Za-z_][\w.+-]*):[A-Z]+=(.*)$", line)
        if m:
            values[m.group(1)] = m.group(2).strip()
    return values


def _find_cache(project: Path) -> Path | None:
    """The project's existing build folder (`CMakeCache.txt` up to two levels down) that was made
    from this source folder, else any; the newest wins."""
    found = []
    for pattern in ("*/CMakeCache.txt", "*/*/CMakeCache.txt"):
        found += [p for p in project.glob(pattern) if not p.parts[len(project.parts)].startswith(".")]
    if not found:
        return None
    def own(p: Path) -> bool:
        home = _read_cache(p).get("CMAKE_HOME_DIRECTORY", "")
        return bool(home) and os.path.normcase(os.path.abspath(home)) == os.path.normcase(str(project.resolve()))
    return max(found, key=lambda p: (own(p), p.stat().st_mtime))


def _exists(path: str | None) -> str | None:
    return Path(path).as_posix() if path and Path(path).is_file() else None


def _newest(pattern: str) -> str | None:
    """The match with the highest version numbers in its path (mingw1310 over mingw810)."""
    hits = sorted(glob.glob(pattern), key=lambda p: [int(n) for n in re.findall(r"\d+", p)])
    return Path(hits[-1]).as_posix() if hits else None


def detect_tools(project: Path) -> tuple[dict, list[str]]:
    """The toolchain for the project's build: PATH first, then the project's existing build folder
    (`CMakeCache.txt`: generator, compiler, `CMAKE_PREFIX_PATH`, build type, the project's own
    options), then known install places. Returns (tools, notes)."""
    notes = []
    cache_path = _find_cache(project)
    cache = _read_cache(cache_path) if cache_path else {}
    if cache_path:
        notes.append(f"toolchain from {cache_path.parent.relative_to(project).as_posix()}/CMakeCache.txt")
    cmake = (_exists(shutil.which("cmake")) or _exists(cache.get("CMAKE_COMMAND"))
             or next((p for p in map(_exists, KNOWN_CMAKE) if p), None))
    generator = cache.get("CMAKE_GENERATOR") or None
    make = _exists(cache.get("CMAKE_MAKE_PROGRAM"))
    if not generator:
        ninja = _exists(shutil.which("ninja")) or next((p for p in map(_exists, KNOWN_NINJA) if p), None)
        if ninja:
            generator, make = "Ninja", ninja
    cxx = (_exists(cache.get("CMAKE_CXX_COMPILER"))
           or next((_exists(shutil.which(n)) for n in ("c++", "g++", "clang++") if shutil.which(n)), None)
           or _newest(KNOWN_CXX))
    cmake_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in _cmake_files(project))
    prefix = cache.get("CMAKE_PREFIX_PATH")
    if not prefix and re.search(r"find_package\s*\(\s*Qt[56]?\b", cmake_text) and cxx and "/Qt/Tools/mingw" in cxx:
        prefix = _newest(KNOWN_QT)
    defines = []
    for name, value in (("CMAKE_CXX_COMPILER", cxx), ("CMAKE_C_COMPILER", _exists(cache.get("CMAKE_C_COMPILER"))),
                        ("CMAKE_MAKE_PROGRAM", make), ("CMAKE_PREFIX_PATH", prefix),
                        ("CMAKE_BUILD_TYPE", cache.get("CMAKE_BUILD_TYPE"))):
        if value:
            defines.append(f"{name}={value}")
    options = list(dict.fromkeys(re.findall(r"^\s*option\s*\(\s*([A-Za-z_]\w*)", cmake_text, re.M)))
    defines += [f"{o}={cache[o]}" for o in options if cache.get(o)]
    paths = [str(Path(p).parent.as_posix()) for p in (cmake, cxx, make) if p]
    paths += [Path(p, "bin").as_posix() for p in (prefix or "").split(";") if p and Path(p, "bin").is_dir()]
    tools = {"cmake": cmake, "generator": generator, "path": list(dict.fromkeys(paths)), "define": defines}
    return tools, notes


def setup_check(ctx) -> tuple[str | None, str]:
    """(cmake version or None, the one-line message)."""
    tools, notes = detect_tools(ctx.root)
    missing = ("cmake: not found; install CMake 3.21 or newer (https://cmake.org) and a C++ compiler, or put "
               "them on PATH, then run setup again (setup installs nothing)")
    if not tools["cmake"]:
        return None, missing
    try:
        code, out = ctx.run([tools["cmake"], "--version"])
    except Exception:   # not installed, didn't start
        code, out = None, ""
    m = re.search(r"cmake version (\d+)\.(\d+)\.(\d+)", out or "") if code == 0 else None
    if not m:
        return None, missing
    version = ".".join(m.groups())
    if tuple(int(x) for x in m.groups()[:2]) < MIN_CMAKE:
        return None, f"cmake: {version} found ({tools['cmake']}), but System Brain needs 3.21 or newer"
    defines = dict(d.split("=", 1) for d in tools["define"])
    parts = [f"cmake: {version} found ({tools['cmake']})", f"generator {tools['generator'] or 'CMake default'}",
             f"compiler {defines.get('CMAKE_CXX_COMPILER', 'CMake default')}"]
    if defines.get("CMAKE_PREFIX_PATH"):
        parts.append(f"prefix path {defines['CMAKE_PREFIX_PATH']}")
    return version, "; ".join(parts + notes)


def setup_detect(project: Path, test_folder: str) -> dict:
    """The project's own CMake library targets (for the task tests to link), the top-level
    CMakeLists.txt when the project has ctest tests (for the full suite), notes."""
    refs, has_tests = [], False
    for path in _cmake_files(project):
        try:
            rel = path.relative_to(project / test_folder)
            if rel.parts and _TASK_FOLDER.fullmatch(rel.parts[0]):
                continue
        except ValueError:
            pass
        text = re.sub(r"#.*", "", path.read_text(encoding="utf-8", errors="replace"))
        for name, rest in re.findall(r"\badd_library\s*\(\s*([A-Za-z0-9_.+-]+)([^)]*)\)", text):
            if not re.search(r"\b(IMPORTED|ALIAS)\b", rest) and name not in refs:
                refs.append(name)
        has_tests = has_tests or bool(re.search(r"\b(add_test|gtest_discover_tests|gtest_add_tests|"
                                                r"catch_discover_tests|doctest_discover_tests)\s*\(", text))
    tools, _ = detect_tools(project)
    notes = [] if (project / "CMakeLists.txt").is_file() else [
        "no CMakeLists.txt at the project root: C++ tests run once the project has a CMake build"]
    if tools["cmake"]:
        notes.append(f"toolchain, written to {FACTS} at apply (if it is wrong: put the right tools on PATH, or "
                     f"fix these lines there after apply):\n"
                     + "\n".join(f"  {line}" for line in tools_lines(tools)))
    return {"refs": refs, "test_projects": ["CMakeLists.txt"] if has_tests and (project / "CMakeLists.txt").is_file()
            else [], "notes": notes}


def _write_tools(project: Path, tools: dict) -> bool:
    path = project / FACTS
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    kept = [l for l in text.splitlines() if not l.startswith("cpp_")]
    while kept and not kept[-1].strip():
        kept.pop()
    new = "\n".join(kept + [""] + tools_lines(tools)) + "\n"
    if new == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    return True


def setup_apply(ctx, project: Path, test_folder: str, refs: list[str], templates: Path) -> tuple[list[str], list[str]]:
    """Write the toolchain into Workflow/project.md, <test_folder>/sb_tests.cmake (or add missing
    library targets to it; never overwrite it) and sb_check.h, then configure the project once
    with the task tests added. Returns (touched files, lines)."""
    version, line = setup_check(ctx)
    if version is None:
        return [], [line]
    tools, _ = detect_tools(project)
    touched = [FACTS] if _write_tools(project, tools) else []
    tests = project / test_folder
    shared = tests / SHARED_PROJECT
    if not shared.is_file():
        text = (templates / "Tests" / SHARED_PROJECT).read_text(encoding="utf-8")
        tests.mkdir(parents=True, exist_ok=True)
        shared.write_text(text.replace("{libraries}", " ".join(refs)), encoding="utf-8")
        touched.append(f"{test_folder}/{SHARED_PROJECT}")
    else:
        text = shared.read_text(encoding="utf-8")
        m = _LIBS_LINE.search(text)
        have = m.group(1).split() if m else []
        missing = [r for r in refs if r not in have]
        if m and missing:
            shared.write_text(text[:m.start()] + f"set(SB_TEST_LIBS {' '.join(have + missing)})" + text[m.end():],
                              encoding="utf-8")
            touched.append(f"{test_folder}/{SHARED_PROJECT}")
    if not (tests / HELPER).is_file():
        shutil.copyfile(templates / "Tests" / HELPER, tests / HELPER)
        touched.append(f"{test_folder}/{HELPER}")
    if not (project / "CMakeLists.txt").is_file():
        return touched, [line + ", no CMakeLists.txt at the project root yet: configure skipped"]

    run_ctx = types.SimpleNamespace(root=project, tests=tests, tmp=ctx.tmp, timeout=ctx.timeout, run=ctx.run)
    try:
        _configure(run_ctx, read_tools(project), project)
        line += ", configure ok"
    except Exception as e:
        line += f", configure failed ({e}):\n{getattr(e, 'output', '')[-2000:]}"
    return touched, [line]
