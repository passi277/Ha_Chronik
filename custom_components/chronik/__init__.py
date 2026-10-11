"""Chronik: a calendar of everything that happened in the garden."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import ChronikCoordinator

PLATFORMS = [Platform.CALENDAR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type ChronikConfigEntry = ConfigEntry[ChronikCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services, websocket API and the dashboard card."""
    from .frontend import async_register_card  # noqa: PLC0415
    from .services import async_register_services  # noqa: PLC0415
    from .websocket import async_register_websocket  # noqa: PLC0415

    async_register_services(hass)
    async_register_websocket(hass)
    await async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ChronikConfigEntry) -> bool:
    """Set up a Chronik from a config entry."""
    coordinator = ChronikCoordinator(hass, entry)
    await coordinator.async_setup()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ChronikConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ChronikConfigEntry) -> None:
    """Delete stored entries when the integration is removed."""
    from .store import ChronikStore  # noqa: PLC0415

    await ChronikStore(hass, entry.entry_id).async_remove()


async def _async_update_listener(hass: HomeAssistant, entry: ChronikConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
