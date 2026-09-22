# AGENTS.md

Rules for coding agents in neuro-san. Follow them and the checks in §6 pass on the first run.

---

## 1. Contribution rules

- Agent networks are data-only HOCON files under [neuro_san/registries/](neuro_san/registries/); `manifest.hocon`
  controls whether a network is `serve`d, `public`ly listed, and exposed via `mcp` — see
  [manifest_hocon_reference.md](docs/manifest_hocon_reference.md).
- `CodedTool`s live under [neuro_san/coded_tools/](neuro_san/coded_tools/), resolved via `AGENT_TOOL_PATH`. Mirror
  the registry's folder layout when a tool belongs to a specific network.
- No secrets in HOCON or code: read them from environment variables, or pass them per request via `sly_data` (see
  [Client-Provided API Keys](docs/agent_hocon_reference.md#client-provided-api-keys)). Never log or print `sly_data`.
- Validate a HOCON file before opening a PR:
  `python -m neuro_san.client.hocon_validator_cli path/to/agent.hocon --verbose` (see
  [hocon_validator_cli.md](docs/hocon_validator_cli.md)).
- Keep the diff focused: no unrequested refactors or reformatting of untouched files. Remove debug prints,
  commented-out code and stray `TODO`s before opening a PR.
- Update the matching reference doc in the same PR when you change documented behavior:
  [agent_hocon_reference.md](docs/agent_hocon_reference.md),
  [manifest_hocon_reference.md](docs/manifest_hocon_reference.md),
  [llm_info_hocon_reference.md](docs/llm_info_hocon_reference.md),
  [toolbox_info_hocon_reference.md](docs/toolbox_info_hocon_reference.md),
  [mcp_service.md](docs/mcp_service.md), [clients.md](docs/clients.md), [tests.md](docs/tests.md), or
  [test_case_hocon_reference.md](docs/test_case_hocon_reference.md). Verify every link in a document you touch.

## 2. Code style

- **One module, one class.** Each `.py` file defines exactly one class (a handful of pre-existing exceptions are
  not precedent). Split helper logic into a separate module rather than adding a second class to an existing file.
- **No module-level functions, no nested functions, no lambdas.** Every function is a method (or `@staticmethod`)
  on the module's class. A helper a method needs becomes another method on the same class; bind arguments with
  `functools.partial` on a method or `@staticmethod` where a lambda would otherwise have been used.
- **No comprehensions.** Use explicit `for` loops instead of list/dict/set/generator comprehensions, even when a
  comprehension would be shorter.
- **Always use type hints.** Every function/method signature needs type hints for all parameters and the return
  type; annotate a variable assignment too when the type isn't obvious from the right-hand side.
- **snake_case** for functions, methods, variables, parameters and attributes; **PascalCase** for classes;
  **UPPER_CASE** for constants. Comment the reason if an external API forces `camelCase`.
- Read dictionary values with `.get()`, never `dict[key]`; plain subscript is fine for assignment
  (`config["key"] = value`).
- Catch the specific exceptions that can be handled at that level. Pylint flags a broad `except Exception`
  (W0718); where one is genuinely needed, add `# pylint: disable=broad-exception-caught` and state why in a comment.
- Never fail silently. Report a missing/unreadable file, malformed input, or an unknown choice with the full
  exception, and log enough to act on.
- Prefer `logger` over `print`, with lazy `%` formatting (`logger.info("Loaded %s", name)`) rather than
  f-strings.
- Use accessors, not internals: do not read another class's attributes directly and do not `isinstance` against
  a concrete class — check the interface, or add an interface method that answers the question.
- **Docstrings on every class, function and method.** A class docstring explains its purpose and
  responsibilities. A function/method docstring covers what it does, its parameters, its return value, and any
  exception it raises, in this exact format:

  ```text
  """
  <summary of what the method does>

  :param <name>: <description>
  :param <name>: <description>
  :return: <description>
  """
  ```

  One `:param` line per parameter, in order, using its exact name. Omit `:return:` only when the method returns
  `None`. Add `:raises <ExceptionType>: <description>` after `:return:` if the method can raise something worth
  documenting.
- Mark overridden methods with `@override` (`from typing_extensions import override`). Comment the non-obvious:
  threading/lifecycle behavior and the reason behind a design decision — not what a line already says.

## 3. Testing

- **One test module per class, named after it.** Tests for `some_module.py` (class `SomeClass`) live in
  `test_some_module.py` as the single class `TestSomeClass`, mirroring the source path under `tests/`. Every
  `tests/` directory that holds test modules needs an `__init__.py`, or the CI pylint gate silently skips it — see
  [tests.md](docs/tests.md).
- Test classes derive from `unittest.TestCase`, or `unittest.IsolatedAsyncioTestCase` when the class has
  `async def` tests. `IsolatedAsyncioTestCase` runs its own async tests, so do not add `@pytest.mark.asyncio`.
- Use `TestCase` assert methods (`assertEqual`, `assertIs`, `assertIsNone`, `assertIn`, `assertRaises`, and so
  on), never a bare `assert` — they report both operands on failure.
- The Code style rules in §2 apply to tests too: helpers are methods or `@staticmethod`s, never module-level or
  nested functions, and never `lambda`s — bind a mock `side_effect` with `functools.partial` on a
  `@staticmethod` instead.
- Run the basic suite before opening a PR:
  `pytest -v -m "not integration and not smoke and not needs_server" -n auto`. Narrow to one test with
  `pytest -v path/to/test_file.py::TestClassName::test_method_name`. Full marker/command reference:
  [tests.md](docs/tests.md).

## 4. Investigation rules

- **Don't make assumptions.** Before describing how something works, fixing a bug, or claiming a test passes or
  fails, read the relevant source or run the test. Never guess from naming conventions or memory of similar code.
- **Always cite a reference when reporting.** A factual claim about the codebase ("this function does X", "this
  bug is caused by Y") needs the file path and line number(s) backing it. A test result needs the actual command
  run and its output, not a summary from assumption.

## 5. Git workflow

- Branch off `main` with a short, descriptive branch name; never commit directly to `main`.
- **Never commit unless explicitly told to.** Finishing a change, fixing a bug, or completing a feature is not
  implicit permission to `git commit` or `git push`. Staging (`git add`) without committing is fine; ask before
  committing.

## 6. Opening the PR

```bash
python -m neuro_san.client.hocon_validator_cli path/to/agent.hocon --verbose   # HOCON structure, no LLM calls
flake8 neuro_san tests                                                         # style, line length 120
build_scripts/run_pylint.sh                                                   # pylint --rcfile=.pylintrc

export AGENT_TOOL_PATH="./neuro_san/coded_tools"
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}."
pytest -v -m "not integration and not smoke and not needs_server" -n auto     # basic unit tests
```

Notes:

- Line length is 120 for both Python (flake8/pylint) and Markdown.
- To include the `needs_server` tests, start a server first
  (`python -m neuro_san.service.main_loop.server_main_loop`) and drop `and not needs_server`.
  `build_scripts/server_start.sh` does this in CI, but its `apt-get` step only works inside the CI container.
- `build_scripts/run_markdownlint.sh` (`pymarkdown --config ./.pymarkdownlint.yaml scan`) only scans `./docs`
  and `./README.md`. Any other Markdown file, this one included, needs
  `pymarkdown --config ./.pymarkdownlint.yaml scan <path>` run by hand.
- `build_scripts/run_shellcheck.sh` runs `shellcheck` on every `*.sh` file it finds, skipping paths that contain
  `leaf-common`.
- Tests marked `integration` or `smoke` need extra environment variables and are not run on every push — see
  [tests.md](docs/tests.md) for the full breakdown.
