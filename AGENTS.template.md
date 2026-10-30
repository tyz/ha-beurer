<!--
WHEN REUSING THIS FILE
======================
This is a template for a Home Assistant custom integration. Copy it to
AGENTS.md in the new repository and work through this list.

1. Replace every <PLACEHOLDER>.
2. Fill in Project Facts from the actual code, not from memory.
3. Delete the sections marked OPTIONAL that do not apply (transport-specific
   gotchas, protocol notes, external resources, discovery).
4. Rewrite "Dead Ends" for the new repository. Start from the inherited list if
   you are porting a fork, and add every finding that should not be re-litigated.
5. Update the baseline numbers in "Before You Change Anything" once the tests
   exist, and keep them current.
6. Keep the sections marked CORE unchanged. They are the ones that prevent the
   most wasted work and they are transport-agnostic.

A rule of thumb for everything in this file: hold **rules and pointers, not
snapshots**. Do not copy counts, versions, statuses or sizes out of files the
agent can read for itself (quality_scale.yaml, the test run, the manifest). A
duplicated number rots silently and then sends the agent looking for a problem
that does not exist. A pointer cannot rot.

Keep the file short enough to be read in full at the start of every session.
Protocol detail belongs in a separate document that this file points to.
-->

# Project Context & Agent Guidelines

<One paragraph: what this integration does, which device or service it talks to,
and whether it is a fork.> This file is the operating manual for agents working on
it. The wire protocol or API detail lives in `<PROTOCOL_DOC>` and the user-facing
documentation in `README.md`; do not duplicate either of them here.

## Project Facts

<!-- CORE: adapt the values, keep the shape. -->

| | |
|---|---|
| Domain | `<DOMAIN>` — must match `custom_components/<DOMAIN>/` |
| Transport | `<TRANSPORT>` (`<LIBRARY>` `<VERSION>`) |
| Client layer | `<PATH>`; device I/O knows nothing about Home Assistant entities |
| Platforms | `<list>` in a single config entry |
| Discovery | `<mechanism, e.g. manifest matcher / zeroconf / ssdp / dhcp / none>` |
| Update model | `local_push` / `local_polling` / `cloud_polling` — `<what drives state>` |
| Quality scale | `custom_components/<DOMAIN>/quality_scale.yaml` is the source of truth for per-rule status; target tier is `<tier>` |

## Before You Change Anything

<!-- CORE -->

1. Run the commands below first. The expected baseline is green: the full suite
   passes with nothing skipped or xfailed, the type checker reports no issues, and
   the linter is clean. If it is not green, stop and report — do not "fix" a
   failure you did not cause, and never delete or `xfail` a test to get green.
2. Read `README.md`, `<PROTOCOL_DOC>`, `TODO.md` and `quality_scale.yaml`.
3. Skim `git log -20` to absorb the commit style.
4. Check `git status`. Uncommitted work belongs to the user; never overwrite or
   revert it.

## Workflow & Commands

<!-- CORE: adapt the commands. -->

* Run tests: `pytest -v tests/`
* Linting: `pre-commit run --all-files` — run it twice, the first pass may reformat
* Type checking: `mypy custom_components/` (not `mypy .`)
* CI (`.github/workflows/ci.yml`) runs the same checks on every pull request:
  `pre-commit`, `mypy`, `pytest`, and a `manifest` job that validates the domain,
  the tag/version match, and that all translation files stay key-synced with
  `strings.json`.

## How To Change Code

<!-- CORE: do not weaken. These rules exist because ignoring them has cost hours
     and real work. They are not style preferences. -->

* **Prefer the `edit` tool over Python string surgery.** `edit` fails loudly when
  an anchor is missing or ambiguous; `s.replace()` silently replaces the wrong
  occurrence. Use a script only for genuinely repetitive, line-local changes
  (renaming a symbol across files), never for structural edits.
* **Never re-indent a block with find-and-replace.** If a change moves a block by
  one indentation level, replace the whole function in a single exact edit, or
  extract a helper so no re-indentation is needed. Do not chain `s.replace()`
  calls to repair indentation afterwards.
* **A script that prints `patched` proves nothing.** After any edit that touches
  more than about ten lines: run the formatter, run the linter, compile the
  touched file, then read `git diff`. Only the diff and the tests are evidence.
* **Do not re-read large files.** Use `grep -n -A/-B` for context and
  `sed -n '120,180p'` for a slice. Re-reading a large file after every edit is the
  single largest avoidable cost.
* **Do not split commits retroactively.** Decide the commit boundaries before
  editing and stage as you go. If the work is already mixed, one honest commit
  beats a patch-and-revert dance; say so in the message.
* **Never `git checkout -- <file>`, `git reset --hard` or `git stash drop`.**
  Back up to `/tmp/opencode/` before any bulk operation.
* **Run the linter and the tests after every change**, not once at the end.

## Coding Conventions

<!-- CORE -->

* Type hints are mandatory everywhere.
* Docstrings follow Google style.
* Keep functions small and single-purpose.
* Code style is enforced by `ruff format`.
* Do not add `# type: ignore` or `cast()` to silence a finding; fix the cause or
  use the correct type.

## Home Assistant Guidelines

<!-- CORE -->

* **Asynchronous execution:** never run blocking I/O (network, files,
  `time.sleep()`) on the event loop. Use native `async`/`await` or
  `hass.async_add_executor_job()`.
* **Dependency management:** do not add or change `requirements` in
  `manifest.json`, or dependencies in `pyproject.toml`, without explicit
  permission.
* **Architecture separation:** communication stays out of entity classes, wrapped
  in a client layer or coordinator.
* **Error handling:** catch raw protocol/socket exceptions at the boundary and
  translate them into `HomeAssistantError`, `ConfigEntryNotReady`, or a domain
  exception that callers can act on. Never log-and-continue when the caller needs
  to know a command failed.
* **Availability:** entities must be `unavailable` whenever the device cannot be
  controlled. "Optimistic but wrong" is worse than "unavailable".
* **Entity unique IDs must be stable.** Never derive them from anything the user
  can change (address, MAC, name). Anything that can change will eventually
  orphan the entity and its automations.
* **Discovery** uses the integration's own stack helpers (for Bluetooth:
  `async_discovered_service_info`, `async_ble_device_from_address`), never a fresh
  scan, or devices behind a proxy are invisible.
* **Quality scale:** `quality_scale.yaml` claims are checked against the code. If
  the code does not do it, the rule is `exempt` with a reason, not `done`.
* **Naming:** always "Home Assistant", two words, never hyphenated.

## Testing

<!-- CORE -->

* State how the suite isolates Home Assistant and whether real hardware is needed.
  `<e.g. the suite mocks Home Assistant in tests/conftest.py; no device needed.>`
* Extend the stubs in `conftest.py` instead of importing Home Assistant into a
  test. To check an API signature, read the installed source under
  `.opencode/.local/lib/python3.14/site-packages/`.
* Stubs must mirror real behaviour, not smooth it over. A stub that hides an
  `AttributeError` also hides the bug.
* Fixtures must be protocol-correct: real layout, real checksums, real byte order.
  Do not invent values.
* Every bug fix needs a test that fails against the previous code. Verify that it
  does before claiming the fix works.
* Never weaken an assertion to make a test pass.

## Platform and Protocol Gotchas

<!-- OPTIONAL: keep only what applies; delete the section for a pure cloud API. -->

* `<rule that bites, phrased as an imperative>`
* `<e.g. never send X before Y, the device hangs>`
* `<e.g. values are 1-100 on the wire, 0 means "off" and uses a different command>`

## Dead Ends — Do Not Re-Investigate

<!-- CORE: this is the highest-value section, and the one nobody writes.
     One line per settled question, with the conclusion. -->

* `<theory that was disproven>` — disproven; the actual cause was `<x>`.
* `<change that looks tempting>` — rejected because `<concrete consequence>`.

## Version Control

<!-- CORE -->

* `main` is protected: pull request, passing status checks, linear history. Never
  commit or push to `main` directly.
* Every change starts on its own branch from an up-to-date `main`, named after its
  Conventional Commit prefix: `feat/<slug>`, `fix/<slug>`, `docs/<slug>`,
  optionally with an issue number.
* Every change lands through a pull request whose description states the problem
  and the approach, not just a title.
* Keep the branch current by rebasing, not by merging `main` into it.
* Conventional Commits. One commit per type of change, so a pull request may hold
  several commits. Messages are multi-line: a summary line, then a body with the
  context and the key changes.
* Merge with squash, then delete the branch.
* Other than a `commit`, perform no git actions — push, tag, force-push, deleting
  a remote branch — without the user's permission.

## Documentation

<!-- CORE: adapt the file names. -->

* `README.md` is the user-facing manual: features, installation, troubleshooting.
  Keep it current when behaviour changes.
* `<PROTOCOL_DOC>` is the technical specification. Correct it when reality
  contradicts it.
* `quality_scale.yaml` must stay truthful; see above.
* Comments in code explain *why*, not *what*. If a workaround exists for a firmware
  or API bug, name the bug and where it was found.

## External Resources

<!-- OPTIONAL -->

* `<vendor app / SDK / spec, where it lives, and how to search it efficiently.
  Warn about large trees: narrow the grep to the relevant package.>`
* `TODO.md` and `BUGS.md` are gitignored working lists with the sections
  **New features**, **Improvements** and **Bugs**. Tick items off (`[ ]` to `[x]`)
  only after the user has approved the result.

## Language

<!-- CORE -->

* Code, comments, documentation and commit messages are **English**.
* Keep translations in `translations/XX.json` key-synced with `strings.json` for
  these languages: af, ar, bg, bn, bs, ca, cs, cy, da, de, el, en-GB, en, eo,
  es-419, es, et, eu, fa, fi, fr, fy, ga, gsw, he, hi, hr, hu, hy, id, is, it, ja,
  ka, ko, lb, lt, lv, mk, ml, nb, ne, nl, nn, pl, pt-BR, pt, ro, ru, sk, sl, sq,
  sr-Latn, sr, sv, ta, th, tr, uk, ur, vi, zh-Hans, zh-Hant. CI enforces this.

## Your Environment

<!-- CORE: adapt to the project's container or dev setup. -->

* `<OS/arch>`, Python `<version>`.
* You run in an OCI container. Only `/project` and `/project/.opencode` (`$HOME`)
  survive a restart; installed packages live in `.opencode/.local`.
* `<library-specific import or API traps>`
* `<framework API traps, e.g. an attribute that raises before setup>`
* Ask for missing tooling instead of working around it.

## Reporting

<!-- CORE -->

When you finish, report what you **verified**, not what you intended: the exact
commands and their results, what changed in behaviour, and what remains open. If
something failed or was skipped, say so explicitly.
