---
name: Home Assistant translations
description: Use when a user-visible string changes (config flow title, entity name, abort or error reason), when adding or removing a translation key, or when CI reports that a translations file drifted from strings.json.
---

# Keep the translation files key-synced

`custom_components/beurer/strings.json` is the reference. Every file in
`custom_components/beurer/translations/` must contain exactly the same key paths,
because the `manifest` job in CI flattens both and fails on any missing or extra
key. `AGENTS.md` lists the languages.

## The rule that matters

**Never overwrite an existing translated value.** These are real translations,
not generated copies, so a key that is present is somebody's work. Add keys that
are absent, and remove a key only when it was removed from `strings.json`.

## Procedure

1. Change `strings.json` first. Only then touch `translations/`.
2. Report the drift, writing nothing:

       python3 .agents/skills/ha-translations/scripts/check_translations.py

3. Add the missing keys, copying the English value into every file that lacks
   them. This never modifies an existing value:

       python3 .agents/skills/ha-translations/scripts/check_translations.py --fix

4. Read `git diff --stat`. Expect additions only. A deletion means the script
   touched existing text: that is a bug, so stop and report it — do not repair
   it by hand.
5. If you removed a key from `strings.json` on purpose, drop the leftovers:

       python3 .agents/skills/ha-translations/scripts/check_translations.py --prune-extra

   Use this only when the reported extras are exactly the keys you deleted. It
   deletes anything absent from `strings.json`, including a value someone meant
   to keep, when `strings.json` itself is wrong.
6. Re-run the plain check. It must exit 0 and report that every file matches.
7. `pre-commit run --all-files` and `pytest -v tests/`.

## Notes

- The script compares dotted paths including intermediate objects, the same way
  the CI job does, and reproduces the files byte for byte when nothing changes.
- An added key lands in the position it has in `strings.json`, so the diff stays
  additions-only even when the key was missing rather than new.
- `en.json`, `en-GB.json` and a few others legitimately equal the English text.
  Never "fix" that by inventing a translation.
- Never regenerate a file from scratch with a fresh `json.dump`: that reorders
  keys and produces a diff in every file even where nothing changed.
- Entity names live under `entity.<platform>.<translation_key>.name` in
  `strings.json`. The key must match `_attr_translation_key` on the entity class.
