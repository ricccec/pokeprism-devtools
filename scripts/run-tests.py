#!/usr/bin/env python3
"""Run the test suite, and know which failures are already known.

    python scripts/run-tests.py             # everything, in parallel
    python scripts/run-tests.py --fast      # everything except the slow ones
    python scripts/run-tests.py -k family   # just the ones whose name matches
    python scripts/run-tests.py -v          # print every test's output

The tests are plain scripts, not pytest: each prints `ok`/`FAIL` lines and exits
non-zero. That needs no framework, and this is not one — it is a loop plus the
four facts a person otherwise has to remember, each of which has cost somebody
time:

**The bytecode cache must be cleared first.** A stale `.pyc` once faked a
passing result, with matching size and mtime, and cost half a day. So the caches
go before the loop and `PYTHONDONTWRITEBYTECODE=1` keeps new ones from
appearing.

**`test_lib` is not broken; it is a smoke test of a real build.** It calls
`find_repo_root()` with no argument, so from this repo it dies looking for a
`Makefile` beside a `main.asm` and gets recorded as a permanent red. Given a cwd
inside a game tree it passes. It is run there, and reported as *skipped* — not
passed — when no such tree is on this machine.

**Two reds are true reports, and the list is asserted in both directions.** A
runner that only forgives known failures rots: the entry outlives the bug, and
the day the test starts passing nobody notices. So a `KNOWN_RED` test that goes
green fails this script, and the fix is to delete its row deliberately. That
shape is why `KNOWN_LEAKS` in `tests/test_products.py` caught six stale rows.

**`test_studio` and `test_studio_tui` fail intermittently in a batch and pass
alone.** The cause is unidentified — separate processes should not share
anything — so the rule is empirical: a flaky test that fails is re-run by
itself, after every other test has finished, and the second answer is the one
reported. Both are printed, because "passed on retry" is a fact about the suite
worth seeing.

`test_studio` was added to that list on 2026-09-22, after a `--fast` run failed
it and the next identical run passed. It is the reason the list is a list: the
first version held only the TUI test, so the one case the retry existed for was
the one case it did not cover.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"


def find_interpreter() -> Path:
    """The interpreter to run each test with.

    `<repo>/.venv/bin/python` is this repo's convention and is preferred, so
    `python3 scripts/run-tests.py` still does the right thing. But it is only a
    convention: a repo carved out of this one has no `.venv`, and neither does a
    checkout whose environment lives somewhere else. Falling back to whatever is
    running this script is both correct and the only portable answer.
    """
    conventional = REPO / ".venv" / "bin" / "python"
    return conventional if conventional.exists() else Path(sys.executable)


VENV_PYTHON = find_interpreter()

#: Where a real pokeprism checkout lives. The tests that read the three game
#: trees spell this path out themselves; this matches their convention rather
#: than inventing a second one, and the environment overrides it.
GAME_TREE = Path(
    os.environ.get("POKEPRISM_TREE", Path.home() / "code/ricccec/pokeprism"))

#: Run these with the cwd inside a game tree, because they locate the tree by
#: walking up for a `Makefile` beside a `main.asm`.
NEEDS_GAME_TREE = {"test_lib"}

#: Failing before this branch started, for a reason that is not the suite's
#: fault. Both are the same drift: the live prism tree has an edit the fixtures
#: predate (MtEmberGateway, db7 against 8, from prism's mt-ember-west edit).
KNOWN_RED = {
    "test_eventheader": "live prism tree drift — MtEmberGateway db7 vs 8",
    "test_maplint": "live prism tree drift — MtEmberGateway db7 vs 8",
}

#: Fails in a batch, passes alone. Re-run by itself before being believed.
FLAKY_IN_BATCH = {"test_studio", "test_studio_tui"}

#: Over two minutes each; the rest of the suite is under a second a file.
#: `--fast` drops these, and says so rather than quietly shrinking the run.
SLOW = {"test_studio_tui"}

DEFAULT_TIMEOUT = 600

OK, RED, FAIL, FIXED, SKIPPED = "ok", "red", "FAIL", "FIXED", "skipped"


@dataclass
class Result:
    name: str
    status: str
    seconds: float
    output: str
    note: str = ""

    @property
    def is_unexpected(self) -> bool:
        return self.status in (FAIL, FIXED)


def clear_bytecode_caches() -> int:
    """Delete every `__pycache__` outside the venv. Returns how many."""
    removed = 0
    for cache in REPO.rglob("__pycache__"):
        if ".venv" in cache.parts:
            continue
        shutil.rmtree(cache, ignore_errors=True)
        removed += 1
    return removed


def select_test_files(pattern: str | None, skip_slow: bool) -> list[Path]:
    chosen = sorted(TESTS.glob("test_*.py"))
    if pattern:
        chosen = [p for p in chosen if pattern in p.stem]
    if skip_slow:
        chosen = [p for p in chosen if p.stem not in SLOW]
    return chosen


def run_one_test(path: Path, timeout: int) -> Result:
    """Execute one test script and classify its exit code against KNOWN_RED."""
    name = path.stem
    if name in NEEDS_GAME_TREE and not GAME_TREE.exists():
        return Result(name, SKIPPED, 0.0, "",
                      f"needs a game tree; none at {GAME_TREE}")

    cwd = GAME_TREE if name in NEEDS_GAME_TREE else REPO
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    started = time.monotonic()
    try:
        done = subprocess.run(
            [str(VENV_PYTHON), str(path)], cwd=cwd, env=env, timeout=timeout,
            capture_output=True, text=True)
        code, output = done.returncode, done.stdout + done.stderr
    except subprocess.TimeoutExpired:
        return Result(name, FAIL, time.monotonic() - started, "",
                      f"no result after {timeout}s")

    return Result(name, classify_exit_code(name, code),
                  time.monotonic() - started, output)


def classify_exit_code(name: str, code: int) -> str:
    """Both directions: an unexpected failure and an unexpected pass both fail.

    A known red that starts passing is not good news to be swallowed — it is a
    row that has to be deleted by hand, and this is the only moment anyone will
    be told about it.
    """
    if name in KNOWN_RED:
        return RED if code else FIXED
    return FAIL if code else OK


def format_result_line(result: Result) -> str:
    return (f"  [{result.status:>7}] {result.name}  {result.seconds:.1f}s"
            f"{'  — ' + result.note if result.note else ''}")


def rerun_flaky_alone(results: list[Result], timeout: int) -> None:
    """Re-run failed flaky tests one at a time, in place, and keep the second
    answer — the batch is over, so nothing else is running now.

    The retry prints its own line. It has to: the batch line is already on
    screen saying the test failed, and a second answer that only reaches the
    exit code leaves a reader looking at a failure the run did not fail on.
    """
    for i, r in enumerate(results):
        if r.name not in FLAKY_IN_BATCH or not r.is_unexpected:
            continue
        print(f"  … {r.name} failed in the batch — re-running it alone")
        retry = run_one_test(TESTS / f"{r.name}.py", timeout)
        retry.note = ("passed alone, so the batch failure was the flake"
                      if retry.status == OK else "failed alone too — real")
        print(format_result_line(retry))
        results[i] = retry


def run_all_tests(paths: list[Path], jobs: int, timeout: int) -> list[Result]:
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(run_one_test, p, timeout) for p in paths]
        results = []
        for future in futures:
            result = future.result()
            print(format_result_line(result))
            results.append(result)
    return results


def print_report(results: list[Result], verbose: bool, skipped_slow: list[str],
                 wall: float) -> None:
    for r in results:
        if r.output and (verbose or r.is_unexpected):
            print(f"\n{'=' * 70}\n{r.name} [{r.status}]\n{'=' * 70}\n{r.output}")

    tally = {s: [r.name for r in results if r.status == s]
             for s in (OK, RED, FAIL, FIXED, SKIPPED)}
    print(f"\n{len(tally[OK])}/{len(results)} ok in {wall:.1f}s"
          f" — {len(tally[RED])} known red, {len(tally[SKIPPED])} skipped")
    if skipped_slow:
        print(f"  not run (--fast): {', '.join(skipped_slow)}")
    for name in tally[SKIPPED]:
        note = next(r.note for r in results if r.name == name)
        print(f"  skipped: {name} — {note}")
    for name in tally[RED]:
        print(f"  known red: {name} — {KNOWN_RED[name]}")
    for r in results:
        if r.note and r.status != SKIPPED:
            print(f"  re-run alone: {r.name} — {r.note}")
    for name in tally[FIXED]:
        print(f"  FIXED: {name} passes now — delete its KNOWN_RED row")
    for name in tally[FAIL]:
        print(f"  FAIL: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-k", dest="pattern", metavar="TEXT",
                        help="only tests whose filename contains TEXT")
    parser.add_argument("--fast", action="store_true",
                        help=f"skip the slow ones ({', '.join(sorted(SLOW))})")
    parser.add_argument("-j", dest="jobs", type=int, default=os.cpu_count(),
                        help="tests to run at once (default: one per core)")
    parser.add_argument("-v", dest="verbose", action="store_true",
                        help="print output from every test, not just failures")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"seconds before a test is called hung "
                             f"(default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args()

    if not VENV_PYTHON.exists():
        print(f"No interpreter at {VENV_PYTHON}. "
              f"Create the venv and `pip install -e .` first.")
        return 2

    paths = select_test_files(args.pattern, args.fast)
    if not paths:
        print(f"No test matches {args.pattern!r}.")
        return 2

    print(f"cleared {clear_bytecode_caches()} __pycache__ directories")
    print(f"running {len(paths)} tests, {args.jobs} at a time\n")

    started = time.monotonic()
    results = run_all_tests(paths, args.jobs, args.timeout)
    rerun_flaky_alone(results, args.timeout)
    wall = time.monotonic() - started

    skipped_slow = sorted(SLOW) if args.fast else []
    print_report(results, args.verbose, skipped_slow, wall)
    return 1 if any(r.is_unexpected for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
