# Project Context & Agent Guidelines

Home Assistant custom integration for the Beurer TL 100 daylight lamp, maintained
as a standalone fork of `Deadolus/ha-beurer`. This file is the operating manual
for agents working on it. The wire protocol lives in `README.bluetooth.md` and the
user-facing documentation in `README.md`; do not duplicate either of them here.

## Project Facts

| | |
|---|---|
| Domain | `beurer` — must match `custom_components/beurer/` |
| Transport | Bluetooth LE via `bleak` 3.x and `bleak-retry-connector` |
| Client layer | `custom_components/beurer/beurer.py`; device I/O knows nothing about Home Assistant entities |
| Platforms | `light`, `number`, `switch`, `sensor` in a single config entry |
| Discovery | `manifest.json` `local_name: "TL100*"` through Home Assistant's Bluetooth stack, so ESPHome proxies work |
| Update model | `local_push`: GATT notifications drive state; the light entity keeps one 60 s status poll as a resync path |
| Quality scale | `custom_components/beurer/quality_scale.yaml` is the source of truth for per-rule status; target tier is Platinum |

## Before You Change Anything

1. Run the commands below first. The expected baseline is green: the full suite
   passes with nothing skipped or xfailed, mypy reports no issues, and pre-commit
   is clean. If it is not green, stop and report — do not "fix" a failure you did
   not cause, and never delete or `xfail` a test to get green.
2. Read `README.md`, `README.bluetooth.md`, `TODO.md` and `quality_scale.yaml`.
3. Skim `git log -20` to absorb the commit style.
4. Check `git status`. Uncommitted work belongs to the user; never overwrite or
   revert it.

## Workflow & Commands

* Run tests: `pytest -v tests/`
* Linting: `pre-commit run --all-files` — run it twice, the first pass may reformat
* Type checking: `mypy custom_components/` (not `mypy .`)
* CI (`.github/workflows/ci.yml`) runs the same checks on every pull request:
  `pre-commit`, `mypy`, `pytest`, and a `manifest` job that validates the domain,
  the tag/version match, and that all translation files stay key-synced with
  `strings.json`.

## How To Change Code

These rules exist because ignoring them has cost hours and real work in this
repository. They are not style preferences.

* **Prefer the `edit` tool over Python string surgery.** `edit` fails loudly when
  an anchor is missing or ambiguous; `s.replace()` silently replaces the wrong
  occurrence. Use a script only for genuinely repetitive, line-local changes
  (renaming a symbol across files), never for structural edits.
* **Never re-indent a block with find-and-replace.** If a change moves a block by
  one indentation level, replace the whole function in a single exact edit, or
  extract a helper so no re-indentation is needed. Do not chain `s.replace()`
  calls to repair indentation afterwards.
* **A script that prints `patched` proves nothing.** After any edit that touches
  more than about ten lines: `ruff format`, `ruff check`, `python -m compileall`
  on the touched file, then read `git diff`. Only the diff and the tests are
  evidence.
* **Do not re-read large files.** Use `grep -n -A/-B` for context and
  `sed -n '120,180p'` for a slice. Re-reading a 1100-line file after every edit is
  the single largest avoidable cost in this project.
* **Do not split commits retroactively.** Decide the commit boundaries before
  editing and stage as you go. If the work is already mixed, one honest commit
  beats a patch-and-revert dance; say so in the message.
* **Never `git checkout -- <file>`, `git reset --hard` or `git stash drop`.**
  Back up to `/tmp/opencode/` before any bulk operation.
* **Run the linter and the tests after every change**, not once at the end.

## Coding Conventions

* Type hints are mandatory everywhere.
* Docstrings follow Google style.
* Keep functions small and single-purpose.
* Code style is enforced by `ruff format`, line length 128.
* Do not add `# type: ignore` or `cast()` to silence a finding; fix the cause or
  use the correct type.

## Home Assistant Guidelines

* **Asynchronous execution:** never run blocking I/O (Bluetooth, network, files,
  `time.sleep()`) on the event loop. Use native `async`/`await` or
  `hass.async_add_executor_job()`.
* **Dependency management:** do not add or change `requirements` in
  `manifest.json`, or dependencies in `pyproject.toml`, without explicit
  permission.
* **Architecture separation:** device communication stays out of entity classes,
  wrapped in a client layer or coordinator.
* **Error handling:** catch raw protocol/socket/BLE exceptions at the boundary and
  translate them into `HomeAssistantError`, `ConfigEntryNotReady`, or a domain
  exception that callers can act on. Never log-and-continue when the caller needs
  to know a command failed.
* **Availability:** entities must be `unavailable` whenever the device cannot be
  controlled. "Optimistic but wrong" is worse than "unavailable".
* **Entity unique IDs must be stable.** Never derive them from anything the user
  can change (address, MAC, name). Anything that can change will eventually
  orphan the entity and its automations.
* **Discovery** uses the integration's own stack helpers
  (`bluetooth.async_discovered_service_info`, `async_ble_device_from_address`),
  never a fresh `BleakScanner.discover()`, or devices behind a proxy are invisible.
* **Quality scale:** `quality_scale.yaml` claims are checked against the code. If
  the code does not do it, the rule is `exempt` with a reason, not `done`.
* **Naming:** always "Home Assistant", two words, never hyphenated.

## Testing

* The suite mocks Home Assistant entirely in `tests/conftest.py`; no real Home
  Assistant and no Bluetooth hardware are needed.
* Extend the stubs in `conftest.py` instead of importing Home Assistant into a
  test. Real Home Assistant cannot always be imported here: optional dependencies
  such as `aiohasupervisor` are missing. To check an API signature, read the
  installed source under `.opencode/.local/lib/python3.14/site-packages/`.
* Stubs must mirror real behaviour, not smooth it over. A stub that hides an
  `AttributeError` also hides the bug (that is how the `runtime_data` crash
  reached production).
* Fixtures must be protocol-correct: real frame layout, real checksums, real byte
  order. Do not invent values.
* Every bug fix needs a test that fails against the previous code. Verify that it
  does before claiming the fix works.
* Never weaken an assertion to make a test pass.

## Protocol and Firmware Gotchas

Full detail is in `README.bluetooth.md`. The rules that bite:

* **Never enable the timer while the lamp is off** — the firmware hangs. Send
  `0x38` before `0x33`, and refuse the command instead of hoping.
* Brightness is **1–100** on the wire. 0 is not a brightness; it disables the
  channel (`0x35`). White is capped at 99 because 100 shifts the lamp to red.
* Hardware events (`0xE8`, `0xEB`, `0xEC`) arrive in bursts of up to five
  retransmissions with non-identical bytes. Deduplicate on opcode **and** a time
  window; an unbounded guard also swallows a genuine second button press.
* Incoming frames are length-validated and the checksum is logged, not enforced.
  This is deliberate: BLE already has a link-layer CRC and the incoming XOR
  convention is unverified. Do not "fix" it into a hard reject.
* Apply the effect before the brightness when turning on the moodlight, otherwise
  the effect overwrites the brightness.

## Dead Ends — Do Not Re-Investigate

Each of these was investigated and settled. Reopening them costs tokens and
changes nothing.

* "The `0xE8` handler stops working after a while" — disproven; the actual cause
  was the sticky duplicate guard.
* "Enforce the incoming checksum" — rejected, see above and `README.bluetooth.md`.
* "Let reconfigure change the MAC address" — rejected: entity unique IDs derive
  from it, so a new address orphans every entity. Reconfigure is name-only.
* "Re-add a reauthentication flow" — removed: BLE has no credentials, nothing
  ever started the flow, and it duplicated reconfigure.

## Version Control

* `main` is protected: pull request, passing status checks, linear history. Never
  commit or push to `main` directly.
* Every change starts on its own branch from an up-to-date `main`, named after its
  Conventional Commit prefix: `feat/moodlight-scenes`, `fix/timer-race`,
  `docs/reconfigure`, optionally with an issue number.
* Every change lands through a pull request whose description states the problem
  and the approach, not just a title.
* Keep the branch current by rebasing, not by merging `main` into it.
* Conventional Commits. One commit per type of change, so a pull request may hold
  several commits. Messages are multi-line: a summary line, then a body with the
  context and the key changes.
* The human merges. Squash, then delete the branch. Do not merge your own pull
  request to "finish" the work: the review gate is the only thing the branch and
  PR workflow adds over pushing to `main`, and merging it yourself removes it.
  Merge only when explicitly asked to, in that message.
* Other than a `commit`, perform no git actions — push, tag, force-push, deleting
  a remote branch — without the user's permission.

## Documentation

* `README.md` is the user-facing manual: features, installation, troubleshooting.
  Keep it current when behaviour changes.
* `README.bluetooth.md` is the protocol specification. Correct it when a capture
  or the decoded app contradicts it.
* `quality_scale.yaml` must stay truthful; see above.
* Documentation and skills hold rules and pointers, not snapshots: never copy a
  count, version or status that the reader can obtain from the code or from a
  test run.
* Comments in code explain *why*, not *what*. If a workaround exists for a
  firmware bug, name the bug and where it was found.

## External Resources

* The decoded LightUp APK is in `com.beurer.connect.lightup-decoded-apk/`
  (large and gitignored). Scanning the whole tree is slow and noisy: narrow
  greps to `smali/com/beurer/connect/lightup/devices/`.
* The TL 100 speaks the **WL90** protocol, so the command table lives in
  `devices/wl90/WL90Bytes.smali`. The classes in `devices/tl100/` only carry the
  name prefix, the GATT UUIDs and the delegation to `WL90Resolver`/`WL90Wrapper`;
  grepping there explains nothing about the protocol.
* `TODO.md` and `BUGS.md` are gitignored working lists with the sections
  **New features**, **Improvements** and **Bugs**. Tick items off (`[ ]` to `[x]`)
  only after the user has approved the result.

## Language

* Code, comments, documentation and commit messages are **English**.
* The conversation with the user is **Dutch** (informal, "je/jouw").
* Keep translations in `translations/XX.json` key-synced with `strings.json` for
  these languages: af, ar, bg, bn, bs, ca, cs, cy, da, de, el, en-GB, en, eo,
  es-419, es, et, eu, fa, fi, fr, fy, ga, gsw, he, hi, hr, hu, hy, id, is, it, ja,
  ka, ko, lb, lt, lv, mk, ml, nb, ne, nl, nn, pl, pt-BR, pt, ro, ru, sk, sl, sq,
  sr-Latn, sr, sv, ta, th, tr, uk, ur, vi, zh-Hans, zh-Hant. CI enforces this.

## Your Environment

* Linux (Debian/RaspberryPi OS, arm64), Python 3.14.
* You run in an OCI container. Only `/project` and `/project/.opencode` (`$HOME`)
  survive a restart; installed packages live in `.opencode/.local`.
* There is no SSH key here. `origin` is SSH and belongs to the human; push and
  fetch over the `origin-https` remote, which authenticates through `gh`.
* `bleak` 3.x has no top-level re-exports: import from `bleak.exc` and
  `bleak.backends.*`.
* As of Home Assistant 2026.10, `probatio` replaces `voluptuous`; its exception is
  `probatio.MultipleInvalid`.
* `ConfigEntry.runtime_data` raises `AttributeError` before setup assigns it; use
  `getattr(entry, "runtime_data", None)` where an unloaded entry is possible.
* Ask for missing tooling instead of working around it.

## Reporting

When you finish, report what you **verified**, not what you intended: the exact
commands and their results, what changed in behaviour, and what remains open. If
something failed or was skipped, say so explicitly.
