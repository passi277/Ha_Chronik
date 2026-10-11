"""Serve the Chronik dashboard card and register it as a Lovelace resource."""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)

CARD_FILE = "chronik-card.js"
CARD_PATH = Path(__file__).parent / "www" / CARD_FILE
CARD_URL = f"/{DOMAIN}/{CARD_FILE}"
CARD_URL_VERSIONED = f"{CARD_URL}?v={VERSION}"
DATA_CARD = f"{DOMAIN}_card_registered"


class ChronikCardView(HomeAssistantView):
    """Deliver the card JavaScript (public, like any frontend module)."""

    url = CARD_URL
    name = f"{DOMAIN}:card"
    requires_auth = False

    def __init__(self, content: bytes) -> None:
        self._content = content

    async def get(self, request: web.Request) -> web.Response:
        """Return the card."""
        return web.Response(
            body=self._content,
            content_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )


def _read_card() -> bytes | None:
    try:
        return CARD_PATH.read_bytes()
    except OSError:
        return None


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve the card, load it on every page and keep the Lovelace resource current."""
    if getattr(hass, "http", None) is None or hass.data.get(DATA_CARD):
        return
    content = await hass.async_add_executor_job(_read_card)
    if content is None:
        _LOGGER.error(
            "Chronik card file %s is missing – the dashboard card cannot be loaded. "
            "Please reinstall the integration",
            CARD_PATH,
        )
        return
    hass.http.register_view(ChronikCardView(content))
    hass.data[DATA_CARD] = True

    if "frontend" in hass.config.components:
        # Imported lazily so the integration also loads without the frontend.
        from homeassistant.components.frontend import add_extra_js_url  # noqa: PLC0415

        add_extra_js_url(hass, CARD_URL_VERSIONED)
    await async_ensure_resource(hass)
    _LOGGER.info("Chronik card served at %s", CARD_URL_VERSIONED)


def _is_chronik_card(url: str) -> bool:
    return url.split("?", 1)[0].endswith(f"/{CARD_FILE}")


async def async_ensure_resource(hass: HomeAssistant) -> None:
    """Create or update the Lovelace resource of the card (storage mode only)."""
    if "lovelace" not in hass.config.components:
        return
    from homeassistant.components.lovelace.const import LOVELACE_DATA  # noqa: PLC0415

    data = hass.data.get(LOVELACE_DATA)
    if data is None or data.resource_mode != "storage":
        return
    resources = data.resources
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True

    existing = [item for item in resources.async_items() if _is_chronik_card(item.get("url", ""))]
    if not existing:
        await resources.async_create_item({"res_type": "module", "url": CARD_URL_VERSIONED})
        return
    first, *duplicates = existing
    if first.get("url") != CARD_URL_VERSIONED or first.get("type") != "module":
        await resources.async_update_item(first["id"], {"res_type": "module", "url": CARD_URL_VERSIONED})
    for item in duplicates:
        await resources.async_delete_item(item["id"])
