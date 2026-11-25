"""System Brain's C# runner (NUnit, `dotnet build` + `dotnet test`, TRX results). Part of the System
Brain templates: don't edit it here (running `/system-brain setup` again replaces it).

The adapter (`sb_adapter.py`) uses the "run" part; `sb_setup.py --lang csharp` the "setup" part.
Stdlib only, and no pytest: setup imports this file with a plain Python. The interface every
runner module has is in `docs/multilang-spec.md`, "Adding a language".
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

NAME = "csharp"                 # --lang csharp, sb_timeout_csharp, failed items "csharp: <reason>"
LABEL = "C#"
KIND = "C# namespace"           # "Native test name: T01_login (C# namespace)"
EXTENSIONS = (".cs",)           # files in a task folder that make it a C# folder
SHARED_PROJECT = "Tests.csproj"  # <test_folder>/Tests.csproj, the one shared test project
PROJECT_SUFFIXES = (".csproj",)  # existing test projects in the full suite
TOOL = "dotnet test"
TIMEOUT = 600                   # seconds per build or test run (sb_timeout_csharp)
GITIGNORE = ("bin/", "obj/")    # build output of the shared project and of the projects it builds

# No build servers or MSBuild nodes left running after a run (they would hold the worktree), and
# English tool output in the evidence.
ENV = {"DOTNET_CLI_UI_LANGUAGE": "en", "DOTNET_NOLOGO": "1", "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
       "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1", "MSBUILDDISABLENODEREUSE": "1",
       "DOTNET_CLI_USE_MSBUILD_SERVER": "0", "UseSharedCompilation": "false"}
_TRX = "{http://microsoft.com/schemas/VisualStudio/TeamTest/2010}"
_OUTCOMES = {"Passed": "passed", "NotExecuted": "skipped", "Inconclusive": "skipped"}   # else failed
_ERROR_LINE = re.compile(r":\s*error\s+\w+\d*:", re.I)


class Failed(Exception):
    def __init__(self, reason: str, output: str = "") -> None:
        super().__init__(reason)
        self.output = output


# --- run (used by the adapter) ----------------------------------------------------------------

def native_name(task_id: str) -> str:
    """`T01-login` -> `T01_login`, the namespace a task's C# tests live in."""
    return task_id.replace("-", "_")


def ignore_dir(path: Path) -> bool:
    """`bin/` and `obj/` next to a .csproj: build output, nothing for pytest to walk."""
    return path.name in ("bin", "obj") and path.is_dir() and any(path.parent.glob("*.csproj"))


def is_test_project(path: Path) -> bool:
    """An existing xUnit, NUnit or MSTest project (it runs under `dotnet test` with TRX)."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False
    return bool(re.search(r"Microsoft\.NET\.Test\.Sdk|<IsTestProject>\s*true|MSTest\.Sdk", text, re.I))


def _build(ctx, project: Path) -> None:
    code, out = ctx.run(["dotnet", "build", str(project), "--nologo", "-v", "q", "-nodeReuse:false",
                         "-p:UseSharedCompilation=false"], env=ENV)
    if code != 0:
        errors = list(dict.fromkeys(l.strip() for l in out.splitlines() if _ERROR_LINE.search(l)))
        raise Failed("build failed", "\n".join(errors) or out)


def _test(ctx, project: Path, test_filter: str | None) -> tuple[int, list[tuple[str, str, str]]]:
    args = ["dotnet", "test", str(project), "--no-build", "--nologo", "--results-directory", str(ctx.tmp),
            "--logger", "trx;LogFileName=results.trx"]
    if test_filter:
        args += ["--filter", test_filter]
    code, out = ctx.run(args, env=ENV)
    trx = ctx.tmp / "results.trx"
    if not trx.is_file():
        raise Failed("no results file", out)
    return code, parse_trx(trx)


def run_tasks(ctx, names: list[str] | None) -> tuple[int, list[tuple[str, str, str]]]:
    """Build the shared project once and run it once, filtered to the given namespaces (None:
    every task's tests). The adapter checks the exact namespace match again."""
    shared = ctx.tests / SHARED_PROJECT
    if not shared.is_file():
        rel = shared.relative_to(ctx.root).as_posix()
        raise Failed(f"{rel} missing; run setup with --lang csharp")
    _build(ctx, shared)
    test_filter = "|".join(f"FullyQualifiedName~{n}." for n in names) if names else None
    return _test(ctx, shared, test_filter)


def run_project(ctx, project: Path) -> tuple[int, list[tuple[str, str, str]]]:
    """An existing test project, all of its tests."""
    _build(ctx, project)
    return _test(ctx, project, None)


def parse_trx(path: Path) -> list[tuple[str, str, str]]:
    """(full name, passed | failed | skipped, message) per test result."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as e:
        raise Failed(f"no results file (unreadable: {e})") from None
    classes = {}
    for test in root.iter(f"{_TRX}UnitTest"):
        method = test.find(f"{_TRX}TestMethod")
        classes[test.get("id")] = method.get("className", "") if method is not None else ""
    results = []
    for res in root.findall(f"{_TRX}Results/{_TRX}UnitTestResult"):
        cls, name = classes.get(res.get("testId"), ""), res.get("testName", "")
        full = name if not cls or name.startswith(cls + ".") else f"{cls}.{name}"   # xUnit names are full already
        info = res.find(f"{_TRX}Output/{_TRX}ErrorInfo")
        message = ""
        if info is not None:
            message = "\n".join(t for t in ((info.findtext(f"{_TRX}Message") or "").strip(),
                                            (info.findtext(f"{_TRX}StackTrace") or "").strip()) if t)
        results.append((full, _OUTCOMES.get(res.get("outcome", ""), "failed"), message))
    return results


# --- setup (used by sb_setup.py --lang csharp) ------------------------------------------------

_SKIP = {"bin", "obj", "node_modules", "Workflow", "packages"}
_REF_MARK = "<!-- System Brain: project references -->"


def setup_check(ctx) -> tuple[str | None, str]:
    """(highest SDK version or None, the one-line message)."""
    try:
        code, out = ctx.run(["dotnet", "--list-sdks"], env=ENV)
    except Exception as e:   # not installed, didn't start
        code, out = None, str(e)
    versions = re.findall(r"^(\d+)\.(\d+)\.(\d+)\S*\s", out or "", re.M) if code == 0 else []
    if not versions:
        return None, ("dotnet: no .NET SDK found; install one (https://dot.net), then run setup again "
                      "(setup installs nothing)")
    best = max(versions, key=lambda v: tuple(int(x) for x in v))
    return ".".join(best), f"dotnet: SDK {'.'.join(best)} found"


def _solution_projects(project: Path) -> list[str] | None:
    """The .csproj paths in the root .sln/.slnx files, or None when there is no solution."""
    solutions = sorted(project.glob("*.sln")) + sorted(project.glob("*.slnx"))
    if not solutions:
        return None
    found = []
    for sln in solutions:
        text = sln.read_text(encoding="utf-8-sig", errors="replace")
        if sln.suffix == ".slnx":
            try:
                paths = [p.get("Path", "") for p in ET.fromstring(text).iter("Project")]
            except ET.ParseError:
                paths = []
        else:
            paths = re.findall(r'^Project\("[^"]*"\)\s*=\s*"[^"]*",\s*"([^"]+)"', text, re.M)
        found += [p.replace("\\", "/") for p in paths if p.lower().endswith(".csproj")]
    return list(dict.fromkeys(found))


def _all_projects(project: Path, test_folder: str) -> list[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(project):
        here = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in _SKIP
                             and not (here == project and d == test_folder))
        found += [(here / f).relative_to(project).as_posix() for f in sorted(filenames) if f.endswith(".csproj")]
    return found


def _frameworks(text: str) -> list[str]:
    values = re.findall(r"<TargetFrameworks?>([^<]*)</TargetFrameworks?>", text)
    return [f.strip() for v in values for f in v.split(";") if f.strip()]


def setup_detect(project: Path, test_folder: str) -> dict:
    """The project's own C# projects to reference, its existing test projects (for the full
    suite), and notes about the ones left out."""
    listed = _solution_projects(project)
    paths = listed if listed is not None else _all_projects(project, test_folder)
    refs, test_projects, notes = [], [], []
    shared = f"{test_folder}/{SHARED_PROJECT}"
    for rel in paths:
        path = project / rel
        if rel == shared:
            continue
        if not path.is_file():
            notes.append(f"{rel}: listed in the solution but missing; left out")
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        frameworks = _frameworks(text)
        if not re.search(r"<Project[^>]*\bSdk\s*=", text) and "<Sdk " not in text:
            notes.append(f"{rel}: an old-style (non-SDK) project can't be referenced; left out")
        elif frameworks and all(re.fullmatch(r"net\d{2,3}", f) for f in frameworks):
            notes.append(f"{rel}: a .NET Framework project can't be referenced; left out")
        elif is_test_project(path):
            test_projects.append(rel)
        else:
            refs.append(rel)
    return {"refs": refs, "test_projects": test_projects, "notes": notes}


def setup_apply(ctx, project: Path, test_folder: str, refs: list[str], templates: Path) -> tuple[list[str], list[str]]:
    """Write <test_folder>/Tests.csproj (or add missing references to it) and build it once,
    which restores the NuGet packages into the global cache. Returns (touched files, lines)."""
    version, line = setup_check(ctx)
    if version is None:
        return [], [line]
    tests = project / test_folder
    shared = tests / SHARED_PROJECT
    includes = [os.path.relpath(project / r, tests).replace("\\", "/") for r in refs]
    touched = []
    if not shared.is_file():
        windows = any(re.search(r"-windows|<Use(WPF|WindowsForms)>\s*true", (project / r).read_text(
            encoding="utf-8-sig", errors="replace"), re.I) for r in refs if (project / r).is_file())
        framework = f"net{version.split('.')[0]}.0" + ("-windows" if windows else "")
        text = (templates / "Tests" / SHARED_PROJECT).read_text(encoding="utf-8")
        text = text.replace("{target_framework}", framework).replace(
            "{references}", "".join(f'    <ProjectReference Include="{i}" />\n' for i in includes))
        tests.mkdir(parents=True, exist_ok=True)
        shared.write_text(text, encoding="utf-8")
        touched.append(f"{test_folder}/{SHARED_PROJECT}")
    else:
        text = shared.read_text(encoding="utf-8-sig")
        missing = [i for i in includes if f'Include="{i}"' not in text]
        if missing:
            lines = "".join(f'    <ProjectReference Include="{i}" />\n' for i in missing)
            if _REF_MARK in text:
                at = text.index("<ItemGroup>", text.index(_REF_MARK)) + len("<ItemGroup>")
                text = text[:at] + "\n" + lines.rstrip("\n") + text[at:]
            else:
                text = text.replace("</Project>", f"  <ItemGroup>\n{lines}  </ItemGroup>\n</Project>")
            shared.write_text(text, encoding="utf-8")
            touched.append(f"{test_folder}/{SHARED_PROJECT}")
    try:
        _build(ctx, shared)
        line += ", first build ok"
    except Exception as e:
        line += f", first build failed ({e}):\n{getattr(e, 'output', '')[-2000:]}"
    return touched, [line]
