---
name: Home Assistant entity
description: Use when adding a new entity or platform to the Beurer integration, or when changing how an existing entity reports state, availability, unique IDs, icons, or device information.
---

# Add or change an entity

The integration is a thin Home Assistant layer over `BeurerInstance`. Protocol
work belongs in `beurer.py`; the entity only translates Home Assistant concepts
into client calls and client state into attributes. If you find yourself building
a frame in an entity class, the change is in the wrong file.

## Order of work

1. **Protocol** — `custom_components/beurer/const.py`, `beurer.py`.
   Add a `CMD_*` constant only if the device has a new opcode. Add an
   `async def set_<thing>(...)` on `BeurerInstance` that returns after the write
   and raises `BeurerCommunicationError` on failure. Keep the ordering rules in
   `AGENTS.md` in mind: an effect must be applied before a brightness, and the
   timer must never be enabled while the lamp is off.

2. **State** — `beurer.py`.
   The instance owns the state: a private `_<thing>` field plus a property.
   Device-originated changes update that field in `notification_handler` and end
   with `self.trigger_entity_update()`. Command-originated changes may update it
   directly, but must still call `trigger_entity_update()` so every entity stays
   in sync.

3. **Entity class** — `custom_components/beurer/<platform>.py`.
   Match the existing classes, not the Home Assistant tutorial:

   ```python
   class BeurerThing(Entity):
       _attr_has_entity_name = True
       _attr_translation_key = "thing"
       _attr_should_poll = False

       def __init__(self, instance: BeurerInstance, name: str, entry_id: str) -> None:
           self._instance = instance
           self._entry_id = entry_id
           self._attr_unique_id = f"{instance.mac}_thing"
           self._unregister_callback: Callable[[], None] | None = None

       @override
       async def async_added_to_hass(self) -> None:
           self._unregister_callback = self._instance.register_update_callback(self.async_write_ha_state)

       @override
       async def async_will_remove_from_hass(self) -> None:
           if self._unregister_callback is not None:
               self._unregister_callback()
               self._unregister_callback = None

       @property
       @override
       def available(self) -> bool:
           return self._instance.available
   ```

   Hard rules, each of which has bitten this project:
   - `unique_id` is derived from `instance.mac` plus a literal suffix. Never from
     the name, the address the user can edit, or the config entry title.
   - `_attr_should_poll = False` for anything driven by notifications; the light
     is the only entity with a poll, and it exists as a resync path.
   - `available` follows the instance. An entity that reports a state while the
     lamp is unreachable is worse than one that is unavailable.
   - Catch `(BeurerCommunicationError, BleakError, TimeoutError, OSError)` in
     async command methods and raise `HomeAssistantError` with a message the user
     can act on.

4. **Strings** — `strings.json` under `entity.<platform>.<translation_key>.name`,
   then every translation file. Load the `ha-translations` skill; it is mechanical
   and CI-enforced.

5. **Icons** — `icons.json`, same `entity.<platform>.<translation_key>` shape, when
   the default icon is wrong.

6. **Quality scale** — open `quality_scale.yaml` and check the rules this entity
   touches (`entity-unique-id`, `has-entity-name`, `entity-translations`,
   `entity-category`, `entity-device-class`, ...). If the code does not satisfy a
   rule, mark it `exempt` with a reason. Never mark `done` on the strength of the
   tutorial.

7. **README** — the entity tables under *Supported Features* are user-facing
   documentation; add the entity there or the docs lie.

8. **Tests** — `tests/test_<platform>.py`. One test per behaviour that can
   regress. Follow `tests/test_light.py`, and use the `beurer_instance` fixture
   from `tests/conftest.py`.

9. **Verify** — do not claim success without all three:

       pytest -v tests/
       mypy custom_components/
       pre-commit run --all-files

## When changing an existing entity instead

Check the four things that silently break users: a changed `unique_id` orphans
the entity and its automations, a changed `translation_key` renames it, a new
required attribute can make it unavailable, and a new `should_poll = True`
hammers a device that sleeps. Prefer adding an attribute over renaming one.
