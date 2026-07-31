#!/bin/bash

# Copyright © 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# END COPYRIGHT

# Create a local virtual environment for running/developing the neuro-san
# service on FREE-THREADED CPython 3.14t (no-GIL). This script mirrors the
# choices made in the py314t deployment container build (where applicable):
#
#   * The free-threaded interpreter is provisioned with `uv` (there is no
#     official python:3.14t image or, usually, a system 3.14t interpreter).
#   * The in-house libraries leaf-common and leaf-server-common are built and
#     installed FROM LOCAL SOURCE (never PyPI); their two lines are stripped
#     from requirements.txt so the resolver does not fetch them from the index.
#   * orjson (transitive via langsmith / langgraph-sdk) refuses to build under a
#     free-threaded interpreter unless ORJSON_BUILD_FREETHREADED is set, so we
#     set it.
#
# neuro-san itself is NOT installed into the venv (doing so would pull leaf-*
# from PyPI); run it from the repo source via PYTHONPATH, exactly as the
# container does. Usage instructions are printed at the end.
#
# Usage:
#   build_scripts/make_venv_py314t.sh [VENV_DIR] [--dev] [--force]
#
#   VENV_DIR   Where to create the venv. Default: <repo>/.venv-py314t
#   --dev      Also install requirements-build.txt (tests, linters, optional
#              LLM providers). These may hit additional cp314t source-build
#              issues; omit for a lean service-only environment.
#   --force    Recreate VENV_DIR if it already exists.
#
# Environment overrides:
#   PYTHON_VERSION           interpreter to provision (default: 3.14t)
#   LEAF_COMMON_DIR          path to local leaf-common     (default: ../leaf-common)
#   LEAF_SERVER_COMMON_DIR   path to local leaf-server-common (default: ../leaf-server-common)
#   LEAF_COMMON_VERSION / LEAF_SERVER_COMMON_VERSION   pin the built versions
#   AUTO_INSTALL_UV=1        install uv automatically if it is missing
#   AUTO_INSTALL_RUST=1      install a Rust toolchain (rustup) automatically if missing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PYTHON_VERSION="${PYTHON_VERSION:-3.14t}"
LEAF_COMMON_DIR="${LEAF_COMMON_DIR:-${REPO_ROOT}/../leaf-common}"
LEAF_SERVER_COMMON_DIR="${LEAF_SERVER_COMMON_DIR:-${REPO_ROOT}/../leaf-server-common}"

VENV_DIR=""
WITH_DEV=0
FORCE=0

function log()  { echo "[make_venv_py314t] $*"; }
function warn() { echo "[make_venv_py314t] WARNING: $*" >&2; }
function die()  { echo "[make_venv_py314t] ERROR: $*" >&2; exit 1; }

function parse_args() {
    for arg in "$@"; do
        case "${arg}" in
            --dev)   WITH_DEV=1 ;;
            --force) FORCE=1 ;;
            -h|--help)
                sed -n '18,52p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
                exit 0
                ;;
            --*) die "unknown option: ${arg}" ;;
            *)
                if [ -z "${VENV_DIR}" ]; then
                    VENV_DIR="${arg}"
                else
                    die "unexpected extra argument: ${arg}"
                fi
                ;;
        esac
    done
    VENV_DIR="${VENV_DIR:-${REPO_ROOT}/.venv-py314t}"
}

function ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        log "uv found: $(uv --version)"
        return
    fi
    if [ "${AUTO_INSTALL_UV:-0}" = "1" ]; then
        log "uv not found; installing (AUTO_INSTALL_UV=1)..."
        tmp_installer="$(mktemp)"
        curl -LsSf https://astral.sh/uv/install.sh -o "${tmp_installer}"
        sh "${tmp_installer}"
        rm -f "${tmp_installer}"
        # The installer drops uv in ~/.local/bin; make it visible now.
        export PATH="${HOME}/.local/bin:${PATH}"
        command -v uv >/dev/null 2>&1 || die "uv install did not put uv on PATH"
    else
        die "uv is required but not installed. Install it with:
       curl -LsSf https://astral.sh/uv/install.sh | sh
   (or set AUTO_INSTALL_UV=1 to let this script do it), then re-run."
    fi
}

function ensure_build_toolchain() {
    # A C compiler is needed for several native deps; Rust is needed for orjson
    # (and possibly pydantic-core) when no cp314t wheel is available.
    command -v cc >/dev/null 2>&1 || command -v gcc >/dev/null 2>&1 \
        || warn "no C compiler (cc/gcc) found; native dependencies may fail to build.
   Linux: install build-essential;  macOS: xcode-select --install"

    if command -v cargo >/dev/null 2>&1; then
        log "cargo found: $(cargo --version)"
        return
    fi
    if [ "${AUTO_INSTALL_RUST:-0}" = "1" ]; then
        log "cargo not found; installing rustup toolchain (AUTO_INSTALL_RUST=1)..."
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
        # shellcheck disable=SC1091
        source "${CARGO_HOME:-${HOME}/.cargo}/env"
        command -v cargo >/dev/null 2>&1 || die "rustup install did not put cargo on PATH"
    else
        die "cargo (Rust) is required to build orjson for free-threaded Python, but was not found.
   Install it with:
       curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
       source \"\$HOME/.cargo/env\"
   (or set AUTO_INSTALL_RUST=1 to let this script do it), then re-run."
    fi
}

function derive_version() {
    # Best-effort "X.Y.Z" from a repo's git tags so the built package version
    # matches reality; falls back to the provided default.
    local repo_dir="$1"
    local default_version="$2"
    local described
    described="$(git -C "${repo_dir}" describe --tags --abbrev=0 2>/dev/null || true)"
    described="$(echo "${described}" | sed -E 's/^v//; s/^([0-9]+(\.[0-9]+)*).*/\1/')"
    if [ -n "${described}" ]; then
        echo "${described}"
    else
        echo "${default_version}"
    fi
}

function main() {
    parse_args "$@"

    [ -f "${REPO_ROOT}/requirements.txt" ] || die "no requirements.txt at repo root ${REPO_ROOT}"
    for d in "${LEAF_COMMON_DIR}" "${LEAF_SERVER_COMMON_DIR}"; do
        [ -f "${d}/pyproject.toml" ] || die "local dependency source not found at '${d}' (no pyproject.toml).
   Set LEAF_COMMON_DIR / LEAF_SERVER_COMMON_DIR to point at the local repos."
    done

    ensure_uv
    ensure_build_toolchain

    local leaf_common_version leaf_server_common_version
    leaf_common_version="${LEAF_COMMON_VERSION:-$(derive_version "${LEAF_COMMON_DIR}" "1.2.43")}"
    leaf_server_common_version="${LEAF_SERVER_COMMON_VERSION:-$(derive_version "${LEAF_SERVER_COMMON_DIR}" "0.1.17")}"

    log "repo root                : ${REPO_ROOT}"
    log "venv dir                 : ${VENV_DIR}"
    log "python                   : ${PYTHON_VERSION} (free-threaded)"
    log "leaf-common source       : ${LEAF_COMMON_DIR} (as ${leaf_common_version})"
    log "leaf-server-common source: ${LEAF_SERVER_COMMON_DIR} (as ${leaf_server_common_version})"
    log "install build/dev reqs   : $([ "${WITH_DEV}" = 1 ] && echo yes || echo no)"

    # Handle an existing venv.
    if [ -e "${VENV_DIR}" ]; then
        if [ "${FORCE}" = 1 ]; then
            log "removing existing ${VENV_DIR} (--force)"
            rm -rf "${VENV_DIR}"
        else
            die "${VENV_DIR} already exists. Pass --force to recreate, or choose another VENV_DIR."
        fi
    fi

    # 1. Provision the free-threaded interpreter and create the venv.
    log "installing free-threaded CPython ${PYTHON_VERSION} via uv..."
    uv python install "${PYTHON_VERSION}"

    log "creating venv at ${VENV_DIR}..."
    # --seed puts pip in the venv for tooling that expects it.
    uv venv --python "${PYTHON_VERSION}" --seed "${VENV_DIR}"

    local venv_python="${VENV_DIR}/bin/python"

    # 2. Build the stripped requirements file (no local leaf lines).
    local req_nolocal
    req_nolocal="$(mktemp)"
    # shellcheck disable=SC2064
    trap "rm -f '${req_nolocal}'" EXIT
    grep -viE '^[[:space:]]*(leaf-common|leaf-server-common)([[:space:]]|[<>=!~;[]|$)' \
        "${REPO_ROOT}/requirements.txt" > "${req_nolocal}"

    # 3. Install everything into the venv.
    #    - local leaf sources are given as paths (pinned; never from PyPI)
    #    - ORJSON_BUILD_FREETHREADED opts orjson into building under 3.14t
    #    - SETUPTOOLS_SCM_PRETEND_VERSION_FOR_* stamps the leaf versions
    local -a install_args=(
        "${LEAF_COMMON_DIR}"
        "${LEAF_SERVER_COMMON_DIR}"
        -r "${req_nolocal}"
    )
    if [ "${WITH_DEV}" = 1 ]; then
        if [ -f "${REPO_ROOT}/requirements-build.txt" ]; then
            install_args+=(-r "${REPO_ROOT}/requirements-build.txt")
        else
            warn "requirements-build.txt not found; skipping --dev extras"
        fi
    fi

    log "installing dependencies (this compiles orjson and possibly others for cp314t)..."
    ORJSON_BUILD_FREETHREADED=1 \
    SETUPTOOLS_SCM_PRETEND_VERSION_FOR_LEAF_COMMON="${leaf_common_version}" \
    SETUPTOOLS_SCM_PRETEND_VERSION_FOR_LEAF_SERVER_COMMON="${leaf_server_common_version}" \
        uv pip install --python "${venv_python}" "${install_args[@]}"

    # 4. Sanity check the resulting environment.
    log "verifying environment..."
    PYTHONPATH="${REPO_ROOT}" "${venv_python}" - <<'PY'
import sys
print("  python              :", sys.version.split()[0], "(" + sys.executable + ")")
gil = getattr(sys, "_is_gil_enabled", None)
print("  free-threaded build :", bool(__import__("sysconfig").get_config_var("Py_GIL_DISABLED")))
print("  GIL enabled now     :", gil() if gil else "n/a")
import leaf_common, leaf_server_common
print("  leaf_common         :", leaf_common.__name__, "OK")
print("  leaf_server_common  :", leaf_server_common.__name__, "OK")
import neuro_san
print("  neuro_san import    : OK (from repo source)")
PY

    print_usage "${venv_python}"
}

function print_usage() {
    local venv_python="$1"
    cat <<EOF

[make_venv_py314t] Done. Virtual environment ready at:
    ${VENV_DIR}

To use it to run the neuro-san service from source:

    source "${VENV_DIR}/bin/activate"
    export PYTHONPATH="${REPO_ROOT}"
    export AGENT_MANIFEST_FILE="${REPO_ROOT}/neuro_san/registries/manifest.hocon"
    export AGENT_TOOL_PATH="${REPO_ROOT}/neuro_san/coded_tools"
    export OPENAI_API_KEY="<your key>"        # demos default to OpenAI

    # The free-threaded build defaults to GIL OFF, but importing a not-yet-safe
    # extension (e.g. orjson) would auto RE-ENABLE it. To match the container,
    # which forces it off, export:
    export PYTHON_GIL=0

    python -m neuro_san.service.main_loop.server_main_loop

Quick GIL check in this venv:
    ${venv_python} -c "import sys, orjson; print('GIL enabled:', sys._is_gil_enabled())"

EOF
}

main "$@"
