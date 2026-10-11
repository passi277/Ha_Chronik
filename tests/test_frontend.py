"""The card is served by the integration and registered as Lovelace resource."""

from __future__ import annotations

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.chronik.const import DOMAIN
from custom_components.chronik.frontend import CARD_URL, CARD_URL_VERSIONED, async_ensure_resource


async def test_card_served_and_resource_managed(hass: HomeAssistant, hass_client_no_auth) -> None:
    """The view returns the card and exactly one up-to-date resource exists."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "lovelace", {})
    resources = hass.data[LOVELACE_DATA].resources
    await resources.async_load()
    resources.loaded = True
    # An outdated and a duplicate resource from earlier versions.
    await resources.async_create_item(
        {"res_type": "module", "url": "/chronik_static/chronik-card.js?v=0.3.1"}
    )
    await resources.async_create_item({"res_type": "module", "url": "https://cdn.example/x/chronik-card.js"})
    await resources.async_create_item({"res_type": "module", "url": "/hacsfiles/other/other-card.js"})

    entry = MockConfigEntry(domain=DOMAIN, options={"ai_entities": ["input_text.x"]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    urls = [item["url"] for item in resources.async_items()]
    assert urls.count(CARD_URL_VERSIONED) == 1
    assert "/hacsfiles/other/other-card.js" in urls
    assert not [u for u in urls if "chronik-card.js" in u and u != CARD_URL_VERSIONED]

    # Idempotent.
    await async_ensure_resource(hass)
    assert [item["url"] for item in resources.async_items()].count(CARD_URL_VERSIONED) == 1

    client = await hass_client_no_auth()
    response = await client.get(CARD_URL)
    assert response.status == 200
    assert response.content_type == "application/javascript"
    assert 'customElements.define("chronik-card"' in await response.text()
