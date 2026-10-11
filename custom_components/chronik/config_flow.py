"""Config and options flow of the Chronik integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    CAT_AI,
    CAT_ALARM,
    CAT_IRRIGATION,
    CAT_MOWING,
    CAT_POOL,
    CAT_RAIN,
    CONF_AI_ENTITIES,
    CONF_AI_IMAGE_DIRS,
    CONF_AI_IMAGE_WINDOW,
    CONF_ALARM_ENTITIES,
    CONF_ALARM_LOG_ARMING,
    CONF_IRRIGATION_ENTITIES,
    CONF_IRRIGATION_METER,
    CONF_IRRIGATION_MIN,
    CONF_MOWING_ENTITIES,
    CONF_MOWING_MERGE,
    CONF_MOWING_MIN,
    CONF_POOL_COUNTERS,
    CONF_POOL_ENTITIES,
    CONF_POOL_THRESHOLD,
    CONF_RAIN_GAP,
    CONF_RAIN_SENSOR,
    CONF_RETENTION_DAYS,
    DEFAULTS,
    DOMAIN,
)

STEP_GENERAL = "general"
SOURCE_STEPS = [CAT_RAIN, CAT_IRRIGATION, CAT_MOWING, CAT_POOL, CAT_ALARM, CAT_AI]


def _entities(domains: list[str], multiple: bool = True) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domains, multiple=multiple))


def _minutes(minimum: float, maximum: float, step: float = 1) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement="min",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


# Per step: option key → (selector, is_entity_field)
STEP_FIELDS: dict[str, dict[str, tuple[Any, bool]]] = {
    CAT_RAIN: {
        CONF_RAIN_SENSOR: (_entities(["sensor"], multiple=False), True),
        CONF_RAIN_GAP: (_minutes(5, 720, 5), False),
    },
    CAT_IRRIGATION: {
        CONF_IRRIGATION_ENTITIES: (
            _entities(["binary_sensor", "switch", "valve", "input_boolean"]),
            True,
        ),
        CONF_IRRIGATION_METER: (_entities(["sensor"], multiple=False), True),
        CONF_IRRIGATION_MIN: (_minutes(0, 60), False),
    },
    CAT_MOWING: {
        CONF_MOWING_ENTITIES: (_entities(["lawn_mower"]), True),
        CONF_MOWING_MERGE: (_minutes(0, 240), False),
        CONF_MOWING_MIN: (_minutes(0, 60), False),
    },
    CAT_POOL: {
        CONF_POOL_ENTITIES: (
            _entities(["timer", "switch", "binary_sensor", "input_boolean", "valve"]),
            True,
        ),
        CONF_POOL_COUNTERS: (_entities(["sensor", "counter", "input_number"]), True),
        CONF_POOL_THRESHOLD: (
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=1000, step=0.1, mode=selector.NumberSelectorMode.BOX)
            ),
            False,
        ),
    },
    CAT_ALARM: {
        CONF_ALARM_ENTITIES: (
            _entities(["alarm_control_panel", "siren", "binary_sensor", "input_boolean", "switch"]),
            True,
        ),
        CONF_ALARM_LOG_ARMING: (selector.BooleanSelector(), False),
    },
    CAT_AI: {
        CONF_AI_ENTITIES: (_entities(["input_text", "sensor", "text"]), True),
        # Optional text: treated like an entity field so it can be cleared.
        CONF_AI_IMAGE_DIRS: (selector.TextSelector(selector.TextSelectorConfig(multiline=True)), True),
        CONF_AI_IMAGE_WINDOW: (_minutes(1, 60), False),
    },
    STEP_GENERAL: {
        CONF_RETENTION_DAYS: (
            selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=3650,
                    step=1,
                    unit_of_measurement="d",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            False,
        ),
    },
}


def _schema(step: str, options: Mapping[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {}
    for key, (sel, is_entity) in STEP_FIELDS[step].items():
        if is_entity:
            # Optional without default so the field can be cleared.
            marker = vol.Optional(key, description={"suggested_value": options.get(key)})
        else:
            marker = vol.Required(key, default=options.get(key, DEFAULTS.get(key)))
        fields[marker] = sel
    return vol.Schema(fields)


def _merge(step: str, options: dict[str, Any], user_input: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(options)
    for key, (_sel, is_entity) in STEP_FIELDS[step].items():
        value = user_input.get(key)
        if is_entity and not value:
            result.pop(key, None)
        elif value is not None:
            result[key] = value
    return result


class ChronikConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Chronik: name, then one page per category."""

    VERSION = 1

    def __init__(self) -> None:
        self._name = "Chronik"
        self._options: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> ChronikOptionsFlow:
        """Return the options flow."""
        return ChronikOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the name."""
        if user_input is not None:
            self._name = user_input[CONF_NAME]
            return await self.async_step_rain()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default=self._name): str}),
        )

    def _source_step(self, step: str, next_step: Callable[[], Any]) -> Any:
        async def handler(user_input: dict[str, Any] | None) -> ConfigFlowResult:
            if user_input is not None:
                self._options = _merge(step, self._options, user_input)
                return await next_step()
            return self.async_show_form(step_id=step, data_schema=_schema(step, self._options))

        return handler

    async def async_step_rain(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Rain source."""
        return await self._source_step(CAT_RAIN, self.async_step_irrigation)(user_input)

    async def async_step_irrigation(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Irrigation sources."""
        return await self._source_step(CAT_IRRIGATION, self.async_step_mowing)(user_input)

    async def async_step_mowing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Mowing sources."""
        return await self._source_step(CAT_MOWING, self.async_step_pool)(user_input)

    async def async_step_pool(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pool sources."""
        return await self._source_step(CAT_POOL, self.async_step_alarm)(user_input)

    async def async_step_alarm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Alarm sources."""
        return await self._source_step(CAT_ALARM, self.async_step_ai)(user_input)

    async def async_step_ai(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """AI finding sources."""
        return await self._source_step(CAT_AI, self._async_finish)(user_input)

    async def _async_finish(self) -> ConfigFlowResult:
        return self.async_create_entry(title=self._name, data={}, options=self._options)


class ChronikOptionsFlow(OptionsFlow):
    """Change sources via a menu with one page per category."""

    def __init__(self) -> None:
        self._options: dict[str, Any] | None = None

    @property
    def options(self) -> dict[str, Any]:
        """Return the options being edited."""
        if self._options is None:
            self._options = dict(self.config_entry.options)
        return self._options

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the menu."""
        return self.async_show_menu(step_id="init", menu_options=[*SOURCE_STEPS, STEP_GENERAL, "save"])

    async def _step(self, step: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        if user_input is not None:
            self._options = _merge(step, self.options, user_input)
            return await self.async_step_init()
        return self.async_show_form(step_id=step, data_schema=_schema(step, self.options))

    async def async_step_rain(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Rain source."""
        return await self._step(CAT_RAIN, user_input)

    async def async_step_irrigation(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Irrigation sources."""
        return await self._step(CAT_IRRIGATION, user_input)

    async def async_step_mowing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Mowing sources."""
        return await self._step(CAT_MOWING, user_input)

    async def async_step_pool(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pool sources."""
        return await self._step(CAT_POOL, user_input)

    async def async_step_alarm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Alarm sources."""
        return await self._step(CAT_ALARM, user_input)

    async def async_step_ai(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """AI finding sources."""
        return await self._step(CAT_AI, user_input)

    async def async_step_general(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """General settings."""
        return await self._step(STEP_GENERAL, user_input)

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Save and reload."""
        return self.async_create_entry(data=self.options)
