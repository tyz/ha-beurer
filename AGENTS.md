# Project Context & Agent Guidelines

This is a Home Assistant integration for the Beurer TL 100 lamp that is no longer receiving the attention it needs. I have now forked it and want to maintain it so that it remains usable in the future. The latest commit is mine; the rest comes from the original repository.

## Stack & Architecture

* Language/runtime: Python 3.14.6 (the version currently used by Home Assistant)

## Workflow & Commands

* Run tests: `pytest -v tests/`
* Linting: `pre-commit run --all-files`
* Type checking: `mypy .`

## Coding Conventions

* Type hints are mandatory everywhere.
* Write docstrings according to Google style.
* Keep functions small and single-purpose.
* Enforce code style using `ruff format`

## Home Assistant Guidelines

* **Asynchronous Execution:** Never execute blocking I/O (e.g., Bluetooth/network communication, file operations, or `time.sleep()`) within the event loop. Always use native `async`/`await` or offload blocking calls via `hass.async_add_executor_job()`.
* **Dependency Management:** Do not add or update package dependencies in `manifest.json` under the `requirements` key without explicit permission.
* **Architecture Separation:** Keep the underlying device communication / API logic cleanly decoupled from Home Assistant entity classes (preferably wrapped in an external client library or dedicated coordinator).
* **Error Handling:** Catch raw protocol/socket/BLE exceptions at the boundary and translate them into standard Home Assistant exceptions (such as `HomeAssistantError` or `ConfigEntryNotReady`).
* **Naming Conventions:** Always use "Home Assistant" (two words, never hyphenated) in code, comments, and documentation.
* **Quality Scale:** Although it's not a requirement for custom integrations it would be nice to try to aim for the Platinum tier. (for details see https://www.home-assistant.io/docs/quality_scale/)

## Version Control

* You may commit your changes in `git` to the `main` branch with a clear commit message. Preferably a multi-line commit messages with a summary line followed by an explanatory body describing the context and key changes.
* Use the Conventional Commits standard for commit messages.
* One commit per type of change; try to avoid grouping multiple tasks/changes into a single commit.
* Other than a `commit`, do not perform any actions in `git` without my permission.

## Restrictions & Constraints

* Never modify dependencies in `pyproject.toml` without explicit permission.
* After each code change, run the linter and unit tests before completing the task.
* Use `.gitignore` for the same purposes as an `.opencodeignore` file.

## Instructions in Other Files

These optional files contain tasks that need to be done (not necessarily right away!). Once you have completed them and I have approved them, you may check them off (`[ ]` becomes `[x]`).

* `TODO.md`: Contains the 3 sections **New features**, **Improvements** and **Bugs**

## Documentation

- `README.md` contains a list of instructions and features. Keep it up to date when adding new features.
- See `README.bluetooth.md` for the BLE protocol specification used by this lamp. Please update it you think there's some info incorrect or missing.

## External Resources

* The Beurer LightUp app APK is located in the `com.beurer.connect.lightup-decoded-apk` directory. In particular, `com.beurer.connect.lightup-decoded-apk/smali/com/beurer/connect/lightup/` will be of interest.

## Language

* Comments, commit messages, and documentation must all be in English.
* Add translations (in `translations/XX.json`) for the following languages: af, ar, bg, bn, bs, ca, cs, cy, da, de, el, en-GB, en, eo, es-419, es, et, eu, fa, fi, fr, fy, ga, gsw, he, hi, hr, hu, hy, id, is, it, ja, ka, ko, lb, lt, lv, mk, ml, nb, ne, nl, nn, pl, pt-BR, pt, ro, ru, sk, sl, sq, sr-Latn, sr, sv, ta, th, tr, uk, ur, vi, zh-Hans, zh-Hant

## Your environment

* Linux, Debian/RaspberryPi OS (arm64)
* You run in an OCI container; let me know if anything that would make your work easier is missing (debs, Python modules, etc)
