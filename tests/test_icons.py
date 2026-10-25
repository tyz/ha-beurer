"""Tests that icons.json matches the entity translation keys."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.beurer.number import BeurerTimerDurationNumber
from custom_components.beurer.sensor import BeurerTimerRemainingSensor
from custom_components.beurer.switch import BeurerTimerSwitch

INTEGRATION_DIR = Path(__file__).parent.parent / "custom_components" / "beurer"


def test_icons_json_has_an_icon_for_every_translated_entity() -> None:
    """Test every entity with a translation key also has an icon."""
    icons = json.loads((INTEGRATION_DIR / "icons.json").read_text())

    expected = {
        "number": BeurerTimerDurationNumber._attr_translation_key,
        "sensor": BeurerTimerRemainingSensor._attr_translation_key,
        "switch": BeurerTimerSwitch._attr_translation_key,
    }

    for platform, translation_key in expected.items():
        assert translation_key is not None, platform
        icon = icons["entity"][platform][translation_key]["default"]
        assert icon.startswith("mdi:"), platform
