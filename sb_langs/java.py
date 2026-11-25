"""System Brain's Java runner (JUnit 5, Gradle, JUnit XML results). Part of the System Brain
templates: don't edit it here (running `/system-brain setup` again replaces it).

The adapter (`sb_adapter.py`) uses the "run" part; `sb_setup.py --lang java` the "setup" part.
Stdlib only, and no pytest: setup imports this file with a plain Python. The interface every
runner module has is in `docs/multilang-spec.md`, "Adding a language".

Gradle is the installed one (no Gradle wrapper). Codex's sandbox has no network, can't write the
user's `~/.gradle`, and can't even use jars there (it runs as another Windows user, who may not
list the user's profile folder, and `javac` needs that). So setup's first build downloads JUnit
and what the project's code needs into a dependency cache of the project's own,
`.gradle/sb-cache` in the main checkout, and every test run reads it read-only
(`GRADLE_RO_DEP_CACHE`), with a Gradle user home of its own (`.gradle/sb-home`).
"""
from __future__ import annotations

import os
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

NAME = "java"                     # --lang java, sb_timeout_java, failed items "java: <reason>"
LABEL = "Java"
KIND = "Java package"             # "Native test name: t01_login (Java package)"
EXTENSIONS = (".java",)           # files in a task folder that make it a Java folder
SHARED_PROJECT = "build.gradle"   # <test_folder>/build.gradle (+ settings.gradle), the shared test build
SETTINGS = "settings.gradle"
PROJECT_SUFFIXES = (".gradle", ".kts")   # the project's own build (settings.gradle) in the full suite
TOOL = "gradle test"
TIMEOUT = 600                     # seconds per Gradle run (sb_timeout_java)
GITIGNORE = ("build/", ".gradle/")   # build output and Gradle's own folders, in the test folder and the project
MARK = "System Brain's shared Java test build"   # first line of both shared build files

# One build, no daemon or build cache left behind or reused, plain output (errors only).
_FLAGS = ["--no-daemon", "--no-build-cache", "--no-configuration-cache", "--console=plain", "-q"]
_JAVAC_ERROR = re.compile(r"\.java:\d+: error:")
_SETTINGS_FILES = ("settings.gradle", "settings.gradle.kts")
_BUILD_FILES = ("build.gradle", "build.gradle.kts")

# Written next to every run's results: turns off what would make Gradle skip or stop a test
# task (up to date, no matching tests, test failures), and sends the JUnit XML to the run's own
# fresh folder. Setup's first build uses `sbResolve`, which downloads the test dependencies.
_INIT = """// System Brain: written for one Gradle run. Only top-level closures: nested ones make class
// files with very long names in the Gradle user home (Windows' 260-character paths).
def sbResults = System.getenv('SB_JAVA_RESULTS')
def sbNothing = { }
def sbTest = { Test t ->
    t.outputs.upToDateWhen(org.gradle.api.specs.Specs.satisfyNone())
    t.ignoreFailures = true
    t.filter.failOnNoMatchingTests = false
    if (t.hasProperty('failOnNoDiscoveredTests')) t.failOnNoDiscoveredTests.set(false)
    if (sbResults) {
        def p = t.project
        def name = (p.rootProject.name + p.path).replace(':', '_') + '_' + t.name
        t.reports.junitXml.outputLocation.set(new File(sbResults, name))
    }
}
def sbProject = { Project p -> p.tasks.withType(Test).configureEach(sbTest) }
def sbResolve = { Task r ->
    def c = r.project.configurations
    r.inputs.files(c.testCompileClasspath, c.testRuntimeClasspath)
    r.doLast(sbNothing)
}
def sbRoot = { Project p ->
    if (p.plugins.hasPlugin('java')) p.tasks.register('sbResolve', DefaultTask, sbResolve)
}
gradle.allprojects(sbProject)
if (gradle.parent == null) gradle.rootProject { it.afterEvaluate(sbRoot) }
"""
_INCLUDE_BUILD = """// The project's own Gradle build: the tests build against its modules. build.gradle names them
// as 'sb.project:<module path with / for :>' ('sb.project:/' is the root project).
includeBuild('{path}') {{
    dependencySubstitution {{
        all {{ d ->
            if (d.requested instanceof ModuleComponentSelector && d.requested.group == 'sb.project') {{
                def m = d.requested.module
                d.useTarget(project(m == '/' ? ':' : ':' + m.replace('/', ':')))
            }}
        }}
    }}
}}
"""
_CACHE = (".gradle", "sb-cache")          # in the main checkout: setup's first build fills it
_USER_HOME = (".gradle", "sb-home")     # per checkout or worktree: Gradle's own files
_REF_MARK = "// System Brain: project references"


class Failed(Exception):
    def __init__(self, reason: str, output: str = "") -> None:
        super().__init__(reason)
        self.output = output


# --- finding Gradle and Java ------------------------------------------------------------------

def _persistent_env() -> dict[str, str]:
    """Windows: PATH, JAVA_HOME and GRADLE_HOME as saved in the registry (machine, then user), so a
    terminal or agent started before Gradle or the JDK was installed still finds them."""
    if os.name != "nt":
        return {}
    import winreg
    found: dict[str, str] = {}
    keys = ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            (winreg.HKEY_CURRENT_USER, "Environment"))
    for hive, sub in keys:
        try:
            with winreg.OpenKey(hive, sub) as key:
                for name in ("Path", "JAVA_HOME", "GRADLE_HOME"):
                    try:
                        value = os.path.expandvars(str(winreg.QueryValueEx(key, name)[0]))
                    except OSError:
                        continue
                    name = name.upper()
                    found[name] = found[name] + os.pathsep + value if name == "PATH" and name in found else value
        except OSError:
            continue
    return found


def _which(name: str, dirs: str | None) -> str | None:
    path = os.pathsep.join(d for d in (dirs or "").split(os.pathsep) if d.strip())
    return shutil.which(name, path=path) if path else None


def _java_ok(home: str | None) -> bool:
    return bool(home) and any(Path(home, "bin", n).is_file() for n in ("java", "java.exe"))


def find_tools(environ: dict | None = None, persistent: dict | None = None) -> tuple[str, dict[str, str]]:
    """(the gradle executable, extra environment so Gradle finds Java). PATH first, then
    GRADLE_HOME / JAVA_HOME, then (Windows) the saved PATH, GRADLE_HOME and JAVA_HOME. Raises
    Failed when one of them isn't there."""
    env = dict(os.environ if environ is None else environ)
    saved = None

    def later() -> dict:
        nonlocal saved
        if saved is None:
            saved = _persistent_env() if persistent is None else persistent
        return saved

    def gradle_in(e: dict) -> str | None:
        return _which("gradle", e.get("PATH")) or (_which("gradle", str(Path(e["GRADLE_HOME"], "bin")))
                                                   if e.get("GRADLE_HOME") else None)

    gradle = gradle_in(env) or gradle_in(later())
    if gradle is None:
        raise Failed("gradle not found")
    if _java_ok(env.get("JAVA_HOME")) or _which("java", env.get("PATH")):
        return gradle, {}
    if _java_ok(later().get("JAVA_HOME")):
        return gradle, {"JAVA_HOME": later()["JAVA_HOME"]}
    java = _which("java", later().get("PATH"))
    if java:
        return gradle, {"PATH": str(Path(java).parent) + os.pathsep + env.get("PATH", "")}
    raise Failed("java not found")


def _main_checkout(root: Path) -> Path:
    """The main checkout of a System Brain worktree (`.worktrees/<ID>`, `.claude/worktrees/<name>`)."""
    if root.parent.name == ".worktrees":
        return root.parent.parent
    if root.parent.name == "worktrees" and root.parent.parent.name == ".claude":
        return root.parents[2]
    return root


def _run_env(ctx) -> tuple[str, dict[str, str]]:
    """The gradle executable and the environment of a test run: a Gradle user home inside the
    checkout (writable in Codex's sandbox) that reads the project's dependency cache."""
    gradle, env = find_tools()
    env["GRADLE_USER_HOME"] = str(ctx.root.joinpath(*_USER_HOME))
    env["GRADLE_RO_DEP_CACHE"] = str(_main_checkout(ctx.root).joinpath(*_CACHE, "caches"))
    env["SB_JAVA_RESULTS"] = str(ctx.tmp / "results")
    return gradle, env


# --- run (used by the adapter) ----------------------------------------------------------------

def native_name(task_id: str) -> str:
    """`T01-login` -> `t01_login`, the package a task's Java tests live in."""
    return task_id.replace("-", "_").lower()


def ignore_dir(path: Path) -> bool:
    """`.gradle/` anywhere, and `build/` next to a Gradle build file: nothing for pytest to walk."""
    if path.name == ".gradle":
        return path.is_dir()
    return (path.name == "build" and path.is_dir()
            and any((path.parent / n).is_file() for n in _BUILD_FILES + _SETTINGS_FILES))


def is_test_project(path: Path) -> bool:
    """The project's own Gradle build (its settings file), whose `test` tasks run as they are.
    System Brain's shared test build is not one."""
    if path.name not in _SETTINGS_FILES:
        return False
    try:
        return MARK not in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _init_script(ctx) -> Path:
    path = ctx.tmp / "sb-init.gradle"
    path.write_text(_INIT, encoding="utf-8")
    return path


def _gradle(ctx, gradle: str, env: dict, build_dir: Path, tasks: list[str]) -> None:
    code, out = ctx.run([gradle, "-p", str(build_dir), *tasks, "-I", str(_init_script(ctx)), *_FLAGS], env=env)
    if code != 0:   # test failures don't fail the build (ignoreFailures): this is a real error
        raise Failed("build failed", _errors(out))


def _errors(out: str) -> str:
    """The compiler errors and Gradle's "What went wrong" lines, or all of the output."""
    lines = [l.strip() for l in out.splitlines()]
    found = [l for l in lines if _JAVAC_ERROR.search(l)]
    if "* What went wrong:" in lines:
        start = lines.index("* What went wrong:") + 1
        end = lines.index("* Try:") if "* Try:" in lines[start:] else len(lines)
        found += [l for l in lines[start:end] if l]
    return "\n".join(dict.fromkeys(found)) or out


def _results(ctx) -> list[tuple[str, str, str]]:
    results = []
    for xml in sorted((ctx.tmp / "results").rglob("*.xml")):
        results += parse_junit(xml)
    return results


def run_tasks(ctx, names: list[str] | None) -> tuple[int, list[tuple[str, str, str]]]:
    """Build and run the shared test build once, filtered to the given packages (None: every
    task's tests). The adapter checks the exact package match again."""
    shared = ctx.tests / SHARED_PROJECT
    if not shared.is_file() or not (ctx.tests / SETTINGS).is_file():
        rel = ctx.tests.relative_to(ctx.root).as_posix()
        raise Failed(f"{rel}/{SHARED_PROJECT} or {rel}/{SETTINGS} missing; run setup with --lang java")
    gradle, env = _run_env(ctx)
    tasks = ["test"]
    for n in names or []:
        tasks += ["--tests", f"{n}.*"]
    _gradle(ctx, gradle, env, ctx.tests, tasks)
    return 0, _results(ctx)


def run_project(ctx, project: Path) -> tuple[int, list[tuple[str, str, str]]]:
    """The project's own Gradle build: every `test` task in it."""
    gradle, env = _run_env(ctx)
    _gradle(ctx, gradle, env, project.parent, ["test", "--continue"])
    return 0, _results(ctx)


def parse_junit(path: Path) -> list[tuple[str, str, str]]:
    """(full name, passed | failed | skipped, message) per <testcase> in a JUnit XML file."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as e:
        raise Failed(f"no results file (unreadable: {path.name}: {e})") from None
    results = []
    for case in root.iter("testcase"):
        cls, name = case.get("classname", ""), case.get("name", "")
        full = f"{cls}.{name}" if cls else name
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is not None:
            message = "\n".join(t for t in ((problem.get("message") or "").strip(), (problem.text or "").strip()) if t)
            results.append((full, "failed", message))
        elif case.find("skipped") is not None:
            results.append((full, "skipped", (case.find("skipped").get("message") or "").strip()))
        else:
            results.append((full, "passed", ""))
    return results


# --- setup (used by sb_setup.py --lang java) --------------------------------------------------

_SKIP = {"build", "out", "bin", "target", "node_modules", "Workflow", "venv", "__pycache__"}
_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)


def setup_check(ctx) -> tuple[str | None, str]:
    """(Gradle version or None, the one-line message)."""
    try:
        gradle, env = find_tools()
        code, out = ctx.run([gradle, "--version"], env=env)
    except Exception as e:   # not installed, didn't start
        missing = "Java (a JDK)" if str(e).startswith("java") else "Gradle"
        return None, (f"gradle: {missing} not found; install Gradle (https://gradle.org/install/) and a JDK, "
                      "then run setup again (setup installs nothing)")
    version = re.search(r"^Gradle (\d+\.\S+)", out or "", re.M) if code == 0 else None
    if not version:
        return None, f"gradle: `gradle --version` failed (exit {code}): {(out or '').strip()[-300:]}"
    jvm = re.search(r"^Launcher JVM:\s*(\S+)", out, re.M)
    line = f"gradle: Gradle {version.group(1)} found" + (f" (Java {jvm.group(1)})" if jvm else "")
    try:
        find_tools(persistent={})
    except Failed:   # Codex's sandbox runs as another Windows user: it sees only the inherited PATH
        line += (" (only in the saved Windows PATH, not in this terminal's: restart the terminal and Claude "
                 "Code before a run, or Codex won't find it)")
    return version.group(1), line


def _settings_file(project: Path) -> Path | None:
    return next((project / n for n in _SETTINGS_FILES if (project / n).is_file()), None)


def _gradle_projects(settings: Path) -> list[str]:
    """`:` and the project paths in the settings file's `include` lines."""
    text = settings.read_text(encoding="utf-8", errors="replace")
    paths = [":"]
    for line in re.findall(r"^\s*include\b\s*\(?(.*)$", text, re.M):
        for name in re.findall(r"""["']([^"']+)["']""", line):
            paths.append(":" + name.strip(":"))
    return list(dict.fromkeys(paths))


def _project_dir(project: Path, gradle_path: str) -> Path:
    return project.joinpath(*[p for p in gradle_path.split(":") if p])


def _source_roots(project: Path, test_folder: str) -> list[str]:
    """Not a Gradle build: the folders the project's own .java files are compiled from, worked
    out from their `package` lines."""
    roots = []
    for dirpath, dirnames, filenames in os.walk(project):
        here = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in _SKIP
                             and not (here == project and d.lower() == test_folder.lower()))
        for f in sorted(filenames):
            if not f.endswith(".java"):
                continue
            match = _PACKAGE.search((here / f).read_text(encoding="utf-8", errors="replace"))
            parts = match.group(1).split(".") if match else []
            root = here
            if parts and list(here.parts[-len(parts):]) == parts:
                root = here.parents[len(parts) - 1]
            rel = root.relative_to(project).as_posix()
            roots.append(rel if rel != "." else ".")
    return list(dict.fromkeys(roots))


def setup_detect(project: Path, test_folder: str) -> dict:
    """What the shared test build compiles against (the project's Gradle modules with Java code,
    or its Java source folders), the project's own build for the full suite when it has tests,
    and notes about what was left out."""
    settings = _settings_file(project)
    refs, test_projects, notes = [], [], []
    if os.name == "nt" and Path.home().resolve() in project.resolve().parents:
        notes.append("warning: the project is inside your user folder; Codex's Windows sandbox can't compile Java "
                     "there (javac must list that folder), so Codex's own test runs fail; move the project "
                     "elsewhere (e.g. D:\\Projects) or give Java tasks to another agent")
    if settings is None:
        if (project / "pom.xml").is_file():
            notes.append("a Maven project (pom.xml): not supported yet; Java tests are not set up")
            return {"refs": [], "test_projects": [], "notes": notes}
        if any((project / n).is_file() for n in _BUILD_FILES):
            notes.append("build.gradle without settings.gradle: add a settings.gradle (Gradle needs one) and "
                         "run setup again; the project's own code is not referenced")
            return {"refs": [], "test_projects": [], "notes": notes}
        roots = _source_roots(project, test_folder)
        return {"refs": roots or ["src"], "test_projects": [], "notes": notes}
    tested = []
    for path in _gradle_projects(settings):
        folder = _project_dir(project, path)
        if not folder.is_dir():
            notes.append(f"{path}: listed in {settings.name} but its folder is missing; left out")
            continue
        if (folder / "src" / "main" / "java").is_dir():
            refs.append(path)
        elif path != ":":
            notes.append(f"{path}: no src/main/java; left out")
        if (folder / "src" / "test").is_dir():
            tested.append(path)
    if tested:
        test_projects.append(settings.name)
        notes.append(f"the full suite runs the project's own tests through {settings.name} "
                     f"(gradle test: {', '.join(tested)})")
    return {"refs": refs, "test_projects": test_projects, "notes": notes}


def _ref_line(ref: str) -> str:
    """One build.gradle line: a Gradle project (`:app`) or a source folder (`../src`)."""
    if ref.startswith(":"):
        return f"dependencies {{ testImplementation 'sb.project:{ref.strip(':').replace(':', '/') or '/'}' }}"
    return f"sourceSets.main.java.srcDir '{ref}'"


def setup_apply(ctx, project: Path, test_folder: str, refs: list[str], templates: Path) -> tuple[list[str], list[str]]:
    """Write <test_folder>/settings.gradle and build.gradle (or add missing references to them)
    and build once, which downloads JUnit and what the referenced code needs into the project's
    dependency cache (`.gradle/sb-cache`) and builds that code. Returns (touched files, lines)."""
    if _settings_file(project) is None and (project / "pom.xml").is_file():
        return [], ["java: a Maven project (pom.xml) is not supported yet; no Java files written"]
    version, line = setup_check(ctx)
    if version is None:
        return [], [line]
    tests = project / test_folder
    up = os.path.relpath(project, tests).replace("\\", "/")
    lines = [_ref_line(r if r.startswith(":") else os.path.relpath(project / r, tests).replace("\\", "/"))
             for r in refs]
    include = _INCLUDE_BUILD.format(path=up) if _settings_file(project) is not None else ""
    touched = []
    tests.mkdir(parents=True, exist_ok=True)
    settings, build = tests / SETTINGS, tests / SHARED_PROJECT
    if not settings.is_file():
        text = (templates / "Tests" / SETTINGS).read_text(encoding="utf-8")
        settings.write_text(text.replace("{include_build}", include), encoding="utf-8")
        touched.append(f"{test_folder}/{SETTINGS}")
    elif include and "includeBuild(" not in settings.read_text(encoding="utf-8"):
        settings.write_text(settings.read_text(encoding="utf-8").rstrip("\n") + "\n" + include, encoding="utf-8")
        touched.append(f"{test_folder}/{SETTINGS}")
    if not build.is_file():
        text = (templates / "Tests" / SHARED_PROJECT).read_text(encoding="utf-8")
        build.write_text(text.replace("{references}", "".join(l + "\n" for l in lines)), encoding="utf-8")
        touched.append(f"{test_folder}/{SHARED_PROJECT}")
    else:
        text = build.read_text(encoding="utf-8")
        missing = [l for l in lines if l not in text]
        if missing:
            add = "".join(l + "\n" for l in missing)
            if _REF_MARK in text:
                at = text.index(_REF_MARK) + len(_REF_MARK)
                text = text[:at] + "\n" + add.rstrip("\n") + text[at:]
            else:
                text = text.rstrip("\n") + "\n" + add
            build.write_text(text, encoding="utf-8")
            touched.append(f"{test_folder}/{SHARED_PROJECT}")
    try:   # with network, into the project's dependency cache that later runs read
        gradle, env = find_tools()
        env["GRADLE_USER_HOME"] = str(project.joinpath(*_CACHE))
        _gradle(ctx, gradle, env, tests, ["sbResolve"])
        line += ", first build ok"
    except Exception as e:
        line += f", first build failed ({e}):\n{getattr(e, 'output', '')[-2000:]}"
    return touched, [line]
