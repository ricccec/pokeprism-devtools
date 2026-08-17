#!/usr/bin/env python3
"""Tests for `scripts/run-tests.py` — the thing that runs everything else.

A runner that miscounts is worse than no runner: every other test in this repo
is read through it, and a classification bug reports a green suite while
something is broken. It also carries the four facts a person would otherwise
have to remember — clear the bytecode caches, give `test_lib` a game-tree cwd,
two reds are known, `test_studio_tui` flakes in a batch — and a fact that stops
being enforced is a fact nobody is told about.

So each of those is seeded here and checked to be caught. **The runner's own
`KNOWN_RED` and `FLAKY_IN_BATCH` lists are patched, never read**, because this
test asserts the *mechanism*: the day `test_maplint` is fixed and its row
deleted, this file must not go red with it.

Nothing is written into `tests/`. The runner's `TESTS` directory is pointed at
a temporary one, so the seeded scripts a real run would collect never exist
beside the real tests — which also means `main()` can be driven end to end
without the outer runner picking up the bait.

    python tests/test_runner.py
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _failures
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}{(': ' + detail) if detail else ''}")
    if not cond:
        _failures += 1


def load_runner():
    """Import `scripts/run-tests.py`, whose name is not an identifier."""
    spec = importlib.util.spec_from_file_location(
        "run_tests", REPO / "scripts" / "run-tests.py")
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves its annotations by looking the module up in
    # sys.modules; without this the class body raises on AttributeError: None.
    sys.modules["run_tests"] = module
    spec.loader.exec_module(module)
    return module


def write_test_script(folder: Path, name: str, body: str) -> Path:
    path = folder / f"{name}.py"
    path.write_text(body)
    return path


PASSES = "print('  [OK] seeded')\n"
FAILS = "import sys\nprint('  [FAIL] seeded')\nsys.exit(1)\n"
HANGS = "import time\ntime.sleep(60)\n"

#: Fails once, then passes — a batch flake, which is what `test_studio_tui`
#: does and what the retry exists for. The marker is not a `test_*.py`, so the
#: runner's own glob never collects it.
FLAKES_ONCE = """
import sys
from pathlib import Path
marker = Path(__file__).with_suffix(".marker")
if marker.exists():
    print('  [OK] passed alone')
    sys.exit(0)
marker.write_text('x')
print('  [FAIL] failed in the batch')
sys.exit(1)
"""


def run_runner_main(runner, tests_dir: Path, argv: list[str]) -> tuple[int, str]:
    """Drive `main()` over `tests_dir` instead of the real one, and capture
    both what it returned and what it printed — the report is half the
    behaviour, and a status nobody prints is a status nobody acts on."""
    real_tests, real_argv = runner.TESTS, sys.argv
    runner.TESTS = tests_dir
    sys.argv = ["run-tests.py", *argv]
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            code = runner.main()
    finally:
        runner.TESTS, sys.argv = real_tests, real_argv
    return code, buffer.getvalue()


def test_classification(runner) -> None:
    """All four corners, and both directions of the known-red list."""
    print("\nclassify_exit_code")
    check("an unknown test exiting 0 is ok",
          runner.classify_exit_code("test_x", 0) == runner.OK)
    check("an unknown test exiting 1 is a FAIL",
          runner.classify_exit_code("test_x", 1) == runner.FAIL)

    runner.KNOWN_RED["test_seeded_red"] = "seeded"
    try:
        check("a known red exiting 1 is expected",
              runner.classify_exit_code("test_seeded_red", 1) == runner.RED)
        check("a known red exiting 0 is FIXED, not silence",
              runner.classify_exit_code("test_seeded_red", 0) == runner.FIXED)
    finally:
        del runner.KNOWN_RED["test_seeded_red"]

    print("\nwhich statuses fail the run")
    for status, unexpected in ((runner.FAIL, True), (runner.FIXED, True),
                               (runner.RED, False), (runner.SKIPPED, False),
                               (runner.OK, False)):
        check(f"{status} is {'' if unexpected else 'not '}unexpected",
              runner.Result("x", status, 0.0, "").is_unexpected is unexpected)


def test_seeded_failure(runner, tmp: Path) -> None:
    print("\na failing test, end to end")
    write_test_script(tmp, "test_seeded", FAILS)
    result = runner.run_one_test(tmp / "test_seeded.py", 30)
    check("run_one_test reports FAIL", result.status == runner.FAIL)
    check("and captures its output", "[FAIL] seeded" in result.output)

    code, report = run_runner_main(runner, tmp, ["-k", "seeded"])
    check("main() exits non-zero", code == 1)
    check("and names the test", "FAIL: test_seeded" in report)
    check("and prints its output, unasked",
          "[FAIL] seeded" in report, "a failure nobody can read is a rerun")


def test_fixed_row(runner, tmp: Path) -> None:
    """The direction that rots if it is not asserted: a known red goes green,
    and the run must fail so somebody deletes the row on purpose."""
    print("\na known red that starts passing")
    write_test_script(tmp, "test_seeded", PASSES)
    runner.KNOWN_RED["test_seeded"] = "seeded"
    try:
        result = runner.run_one_test(tmp / "test_seeded.py", 30)
        check("reports FIXED, not ok", result.status == runner.FIXED)
        code, report = run_runner_main(runner, tmp, ["-k", "seeded"])
        check("main() exits non-zero on it", code == 1)
        check("and says to delete the row",
              "delete its KNOWN_RED row" in report)
    finally:
        del runner.KNOWN_RED["test_seeded"]


def test_timeout(runner, tmp: Path) -> None:
    print("\na hung test")
    write_test_script(tmp, "test_hung", HANGS)
    result = runner.run_one_test(tmp / "test_hung.py", 2)
    check("a timeout is a FAIL, not a pass", result.status == runner.FAIL)
    check("and says how long it waited", "after 2s" in result.note)
    (tmp / "test_hung.py").unlink()


def test_flaky_retry(runner, tmp: Path) -> None:
    """The batch/alone rule, driven by a test that genuinely fails once.

    Written because the real flake would not reproduce on demand:
    `test_studio_tui` passed in the batch on both runs the day the runner was
    added, so this branch had never executed against a failure.
    """
    print("\na test that fails in the batch and passes alone")
    write_test_script(tmp, "test_flaky", FLAKES_ONCE)
    real_flaky = runner.FLAKY_IN_BATCH
    runner.FLAKY_IN_BATCH = {"test_flaky"}
    try:
        code, report = run_runner_main(runner, tmp, ["-k", "flaky"])
        check("the retry is announced, not hidden",
              "re-running it alone" in report)
        check("the second answer is the one reported", "[     ok]" in report)
        check("and it says the batch failure was the flake",
              "passed alone" in report)
        check("so the run passes", code == 0)

        print("\nthe same test failing every time")
        write_test_script(tmp, "test_flaky", FAILS)
        code, report = run_runner_main(runner, tmp, ["-k", "flaky"])
        check("a retry that fails too is called real",
              "failed alone too" in report)
        check("and the run fails", code == 1)
    finally:
        runner.FLAKY_IN_BATCH = real_flaky
        (tmp / "test_flaky.py").unlink(missing_ok=True)
        (tmp / "test_flaky.marker").unlink(missing_ok=True)


def test_game_tree_skip(runner, tmp: Path) -> None:
    """No game tree is *skipped*, never *passed* — the whole point of the row."""
    print("\nthe game-tree cwd")
    real_tree = runner.GAME_TREE
    runner.GAME_TREE = tmp / "no-such-tree"
    try:
        result = runner.run_one_test(REPO / "tests" / "test_lib.py", 30)
        check("an absent tree skips, and does not pass",
              result.status == runner.SKIPPED)
        check("and says why", "needs a game tree" in result.note)
    finally:
        runner.GAME_TREE = real_tree

    if not runner.GAME_TREE.exists():
        print(f"  (no game tree at {runner.GAME_TREE}, skipping the other half)")
        return
    result = runner.run_one_test(REPO / "tests" / "test_lib.py", 120)
    check("given the tree, test_lib passes", result.status == runner.OK,
          "it was never broken — only ever in the wrong directory")


def test_selection(runner) -> None:
    print("\nselection")
    every = [p.stem for p in runner.select_test_files(None, False)]
    fast = [p.stem for p in runner.select_test_files(None, True)]
    check("a full run collects the slow ones", set(runner.SLOW) <= set(every))
    check("--fast drops them", not set(runner.SLOW) & set(fast))
    check("and drops nothing else", set(every) - set(fast) == set(runner.SLOW))
    check("-k filters by filename",
          runner.select_test_files("paths", False)[0].stem == "test_paths")


if __name__ == "__main__":
    runner = load_runner()
    test_classification(runner)
    test_selection(runner)
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_seeded_failure(runner, tmp)
        test_fixed_row(runner, tmp)
        test_timeout(runner, tmp)
        test_flaky_retry(runner, tmp)
        test_game_tree_skip(runner, tmp)
    print(f"\n{'FAILURES: ' + str(_failures) if _failures else 'all ok'}")
    sys.exit(1 if _failures else 0)
