#!/usr/bin/env python3
"""
Build the neuro-san-lite browser bundle.

Two stages, each gate-failing on its own errors:

  1. Lint the Python source under neuro-san-client/src/neuro_san_client/
     against an allowlist of browser-portable imports. Any forbidden import
     fails with a precise file:line pointer.

  2. Drive the TypeScript build of neuro-san-lite-js/ (typecheck + bundle to
     dist/neuro_san_lite.js).

The two sides MUST stay in lockstep: every Python module under
neuro_san_client/ must have a matching neuro_san_lite_js/src/*.ts. The build
fails if either side drifts.

Usage:
    python build_scripts/build_neuro_san_lite.py
    python build_scripts/build_neuro_san_lite.py --lint-only
    python build_scripts/build_neuro_san_lite.py --skip-js   # for Python-only CI
"""
from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Set, Tuple


# Allowlist of imports permitted in neuro_san_client/.  Anything not in this
# set will fail the lint.  Keep this tight: every entry here is something the
# TypeScript port can mirror or shim.
ALLOWED_STDLIB: Set[str] = {
    # Pure data / control flow / typing
    "typing", "typing_extensions",
    "dataclasses", "enum",
    "json", "base64", "hashlib", "re", "copy",
    "asyncio", "contextlib",
    "urllib.parse",
    # Logging is fine — TS has console
    "logging",
    # __future__ imports for forward annotations
    "__future__",
    # Time/datetime sometimes needed in error paths
    "time", "datetime",
}

# Third-party imports allowed in neuro-san-client.
# `httpx` is the only HTTP client; in the browser it's replaced by fetch.
ALLOWED_THIRD_PARTY: Set[str] = {
    "httpx",
}

# Test files get more leeway (pytest, mocks, etc.)
ALLOWED_TEST_EXTRA: Set[str] = {
    "pytest",
    "pytest_asyncio",
    "unittest",
    "unittest.mock",
}

REPO_ROOT = Path(__file__).resolve().parent.parent
PY_PKG_SRC = REPO_ROOT / "neuro-san-client" / "src" / "neuro_san_client"
TS_SRC = REPO_ROOT / "neuro-san-lite-js" / "src"
DIST_DIR = REPO_ROOT / "dist"


def _is_test_file(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def _module_root(name: str) -> str:
    """Top-level module name. 'urllib.parse' -> 'urllib.parse' if in
    ALLOWED_STDLIB, else 'urllib'. We compare against full dotted names
    so 'urllib.parse' is matched exactly."""
    return name


def _check_imports_in_file(path: Path) -> List[str]:
    """Return a list of human-readable error strings for any forbidden imports
    found in `path`. Empty list = clean file."""
    errors: List[str] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{path}: syntax error: {exc}"]

    allow = set(ALLOWED_STDLIB) | set(ALLOWED_THIRD_PARTY)
    if _is_test_file(path):
        allow = allow | ALLOWED_TEST_EXTRA

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if not _import_is_allowed(name, allow):
                    errors.append(
                        f"{path}:{node.lineno}: forbidden import {name!r}. "
                        f"Allowed: stdlib {{...}}, third-party {sorted(ALLOWED_THIRD_PARTY)}."
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level > 0:
                # Relative imports inside the package are always fine.
                continue
            if not _import_is_allowed(mod, allow):
                errors.append(
                    f"{path}:{node.lineno}: forbidden import {mod!r}. "
                    f"Allowed: stdlib {{...}}, third-party {sorted(ALLOWED_THIRD_PARTY)}."
                )
    return errors


def _import_is_allowed(name: str, allow: Set[str]) -> bool:
    """Allow a dotted name iff its top-level OR its full dotted form is
    in the allow set. Relative imports handled separately by caller."""
    if not name:
        return True
    if name in allow:
        return True
    top = name.split(".", 1)[0]
    if top in allow:
        return True
    # Allow imports from our own package.
    if top == "neuro_san_client":
        return True
    return False


def _gather_python_files(root: Path) -> List[Path]:
    if not root.exists():
        return []
    return sorted([p for p in root.rglob("*.py") if "__pycache__" not in p.parts])


def lint_python(verbose: bool = True) -> int:
    py_files = _gather_python_files(PY_PKG_SRC) + _gather_python_files(
        REPO_ROOT / "neuro-san-client" / "tests"
    )
    if not py_files:
        print(f"warning: no Python files found under {PY_PKG_SRC}", file=sys.stderr)
        return 0

    if verbose:
        print(f"[lint] scanning {len(py_files)} python files under "
              f"neuro-san-client/")

    all_errors: List[str] = []
    for path in py_files:
        all_errors.extend(_check_imports_in_file(path))

    if all_errors:
        print("\n[lint] FORBIDDEN IMPORTS FOUND:", file=sys.stderr)
        for err in all_errors:
            print(f"  {err}", file=sys.stderr)
        print(
            "\nIf this dependency genuinely belongs in the browser-portable "
            "client, add it to ALLOWED_STDLIB or ALLOWED_THIRD_PARTY in "
            "build_scripts/build_neuro_san_lite.py AND port it to TypeScript.",
            file=sys.stderr,
        )
        return 1

    if verbose:
        print(f"[lint] OK ({len(py_files)} files clean)")
    return 0


def check_module_pairing(verbose: bool = True) -> int:
    """Each non-test Python module under neuro_san_client/ MUST have a paired
    .ts file under neuro-san-lite-js/src/, and vice versa. Otherwise we have
    a divergent port."""
    if not PY_PKG_SRC.exists() or not TS_SRC.exists():
        if verbose:
            print(f"[pair] skipping (one side missing): "
                  f"py={PY_PKG_SRC.exists()}, ts={TS_SRC.exists()}")
        return 0

    py_modules = {
        p.stem
        for p in PY_PKG_SRC.glob("*.py")
        if p.name != "__init__.py"
    }
    ts_modules = {
        p.stem
        for p in TS_SRC.glob("*.ts")
        if p.name not in ("index.ts", "types.ts")
    }

    missing_ts = py_modules - ts_modules
    missing_py = ts_modules - py_modules

    if missing_ts:
        print(
            "\n[pair] Python modules missing TS port: "
            + ", ".join(sorted(missing_ts)),
            file=sys.stderr,
        )
    if missing_py:
        print(
            "\n[pair] TS modules missing Python source: "
            + ", ".join(sorted(missing_py)),
            file=sys.stderr,
        )
    if missing_ts or missing_py:
        print(
            "\nEvery neuro_san_client/*.py must have a corresponding "
            "neuro-san-lite-js/src/*.ts (and vice versa). Either add the "
            "missing file or rename so the stems match.",
            file=sys.stderr,
        )
        return 1

    if verbose:
        print(f"[pair] OK ({len(py_modules)} module pair{'s' if len(py_modules) != 1 else ''})")
    return 0


def build_typescript(verbose: bool = True) -> int:
    """Run `npm run build` in neuro-san-lite-js/ to typecheck and bundle."""
    ts_dir = REPO_ROOT / "neuro-san-lite-js"
    if not ts_dir.exists():
        if verbose:
            print(f"[ts] skipping (no {ts_dir})")
        return 0

    if not (ts_dir / "node_modules").exists():
        if verbose:
            print("[ts] node_modules missing; running 'npm install'...")
        result = subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund"],
            cwd=ts_dir,
            check=False,
        )
        if result.returncode != 0:
            print("[ts] npm install failed", file=sys.stderr)
            return result.returncode

    if verbose:
        print("[ts] building...")
    result = subprocess.run(
        ["npm", "run", "build"], cwd=ts_dir, check=False
    )
    if result.returncode != 0:
        return result.returncode

    # Copy the built artifact into dist/ at the repo root AND into the demo
    # site so that demo/agent_web_browser_site/ is a self-contained static
    # bundle ready to deploy.
    src_artifact = ts_dir / "dist" / "neuro_san_lite.js"
    if src_artifact.exists():
        DIST_DIR.mkdir(parents=True, exist_ok=True)
        dest = DIST_DIR / "neuro_san_lite.js"
        dest.write_bytes(src_artifact.read_bytes())
        if verbose:
            print(f"[ts] bundle written to {dest}")
        # Mirror into the demo site for one-step local serving + deploy.
        site_dest_dir = REPO_ROOT / "demo" / "agent_web_browser_site"
        if site_dest_dir.exists():
            site_dest = site_dest_dir / "neuro_san_lite.js"
            site_dest.write_bytes(src_artifact.read_bytes())
            if verbose:
                print(f"[ts] bundle also copied to {site_dest}")
    return 0


def test_typescript(verbose: bool = True) -> int:
    """Run `npm test` in neuro-san-lite-js/."""
    ts_dir = REPO_ROOT / "neuro-san-lite-js"
    if not ts_dir.exists():
        if verbose:
            print(f"[ts-test] skipping (no {ts_dir})")
        return 0
    if verbose:
        print("[ts-test] running unit tests...")
    result = subprocess.run(["npm", "test"], cwd=ts_dir, check=False)
    return result.returncode


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lint-only",
        action="store_true",
        help="Run Python lint + pairing check only; skip TS build/tests.",
    )
    parser.add_argument(
        "--skip-js",
        action="store_true",
        help="Skip both TS build and TS tests (for environments without node).",
    )
    parser.add_argument(
        "--skip-js-tests",
        action="store_true",
        help="Skip TS unit tests (still build the bundle).",
    )
    args = parser.parse_args(argv)

    rc = lint_python()
    if rc != 0:
        return rc

    rc = check_module_pairing()
    if rc != 0:
        return rc

    if args.lint_only or args.skip_js:
        return 0

    if not args.skip_js_tests:
        rc = test_typescript()
        if rc != 0:
            print("[build] TS unit tests failed", file=sys.stderr)
            return rc

    rc = build_typescript()
    if rc != 0:
        return rc

    print("\n[build] OK — dist/neuro_san_lite.js is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
