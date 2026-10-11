"""Serve the Chronik dashboard card."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)

CARD_FILE = "chronik-card.js"
URL_BASE = f"/{DOMAIN}_static"


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve the card and load it on every dashboard (no resource setup needed)."""
    if getattr(hass, "http", None) is None or "frontend" not in hass.config.components:
        return
    # Imported lazily so the integration also loads without the frontend.
    from homeassistant.components.frontend import add_extra_js_url  # noqa: PLC0415
    from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

    root = Path(__file__).parent
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(root / "www"), cache_headers=False)]
        )
    except RuntimeError:
        # Already registered (integration reloaded).
        _LOGGER.debug("Static path %s already registered", URL_BASE)
        return
    add_extra_js_url(hass, f"{URL_BASE}/{CARD_FILE}?v={VERSION}")
