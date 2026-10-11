"""Services of the Chronik integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import CATEGORIES, DOMAIN, ORIGIN_SERVICE
from .coordinator import ChronikCoordinator

SERVICE_ADD_ENTRY = "add_entry"
SERVICE_DELETE_ENTRY = "delete_entry"
SERVICE_BACKFILL = "backfill"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"

ADD_ENTRY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required("category"): vol.In(CATEGORIES),
        vol.Required("title"): cv.string,
        vol.Optional("description", default=""): cv.string,
        vol.Optional("start"): cv.datetime,
        vol.Optional("end"): cv.datetime,
        vol.Optional("data", default={}): dict,
        vol.Optional("images", default=[]): vol.All(cv.ensure_list, [cv.string]),
    }
)
DELETE_ENTRY_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string, vol.Required("uid"): cv.string}
)
BACKFILL_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional("days", default=7): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
        vol.Optional("categories"): vol.All(cv.ensure_list, [vol.In(CATEGORIES)]),
    }
)


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> ChronikCoordinator:
    entries = [
        entry for entry in hass.config_entries.async_entries(DOMAIN) if entry.state is ConfigEntryState.LOADED
    ]
    if entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID):
        entries = [entry for entry in entries if entry.entry_id == entry_id]
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_entry")
    if len(entries) > 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="multiple_entries")
    return entries[0].runtime_data


def _local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_util.get_default_time_zone())
    return value


def async_register_services(hass: HomeAssistant) -> None:
    """Register all services of the integration."""

    async def add_entry(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call)
        start = _local(call.data.get("start")) or dt_util.utcnow()
        ev = coordinator.add_entry(
            category=call.data["category"],
            title=call.data["title"],
            description=call.data["description"],
            start=start,
            end=_local(call.data.get("end")),
            data={**call.data["data"], **({"images": call.data["images"]} if call.data["images"] else {})},
            origin=ORIGIN_SERVICE,
        )
        return {"uid": ev.uid}

    async def delete_entry(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call)
        return {"deleted": coordinator.delete_entry(call.data["uid"])}

    async def backfill(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call)
        added = await coordinator.async_backfill(call.data["days"], call.data.get("categories"))
        return {"added": added}

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_ENTRY, add_entry, ADD_ENTRY_SCHEMA, SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_ENTRY, delete_entry, DELETE_ENTRY_SCHEMA, SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, SERVICE_BACKFILL, backfill, BACKFILL_SCHEMA, SupportsResponse.OPTIONAL
    )
