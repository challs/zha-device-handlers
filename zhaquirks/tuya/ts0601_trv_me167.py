"""ME167 TRV devices support."""
import logging
from typing import Optional, Union

import zigpy.types as t
from zhaquirks import Bus, LocalDataCluster
from zhaquirks.const import (
    DEVICE_TYPE,
    ENDPOINTS,
    INPUT_CLUSTERS,
    MODELS_INFO,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
)
from zhaquirks.tuya import (
    TuyaManufClusterAttributes,
    TuyaPowerConfigurationCluster,
    TuyaThermostat,
    TuyaThermostatCluster,
    TuyaUserInterfaceCluster,
)
from zigpy.profiles import zha
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import (
    AnalogOutput,
    Basic,
    BinaryInput,
    Groups,
    Identify,
    OnOff,
    Ota,
    Scenes,
    Time,
)
from zigpy.zcl.clusters.hvac import Thermostat

_LOGGER = logging.getLogger(__name__)

# info from https://github.com/zigpy/zha-device-handlers/issues/1818
# and https://github.com/dresden-elektronik/deconz-rest-plugin/issues/6318
# and https://github.com/twhittock/avatto_me167/blob/main/me167.js

# Display codes:
#  OF - OFF state, anti freezing mode. Press button for 5 seconds to initiate pairing.
#  LA - rod withdraws; mount on radiator then press rotation button to initiate calibration
#  OP - Window is OPen due to temperature drop within 4 minutes
#  Er - error status
#  LC - Child Lock (long press to activate / deactivate)
#  Ad - Anti descale mode (open + close every 2 weeks)

ME167_TEMPERATURE_ATTR = 0x0205  # [0, 0, 0, 210] current room temp (decidegree)
ME167_TARGET_TEMP_ATTR = 0x0204  # [0, 0, 0, 190] target room temp (decidegree)
ME167_TEMP_CALIBRATION_ATTR = 0x0000  # DP 47 -> 2F
ME167_CHILD_LOCK_ATTR = 0x0107  # [0] unlocked [1] child-locked
ME167_ERROR_ATTR = 0x0000  # DP 35 -> 23
ME167_MODE_ATTR = 0x0403  # [0] auto [1] heat [2] off
ME167_STATE_ATTR = 0x0403  # [1] idle [0] heating /!\ inverted
# minimum limit of temperature setting
ME167_MIN_TEMPERATURE_VAL = 5  # degrees
# maximum limit of temperature setting
ME167_MAX_TEMPERATURE_VAL = 30  # degrees
ME167ManufClusterSelf = {}


class CustomTuyaOnOff(LocalDataCluster, OnOff):
    """Custom Tuya OnOff cluster."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.thermostat_onoff_bus.add_listener(self)

    # pylint: disable=R0201
    def map_attribute(self, attribute, value):
        """Map standardized attribute value to dict of manufacturer values."""
        return {}

    async def write_attributes(self, attributes, manufacturer=None):
        """Implement writeable attributes."""

        records = self._write_attr_records(attributes)

        if not records:
            return [[foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)]]

        manufacturer_attrs = {}
        for record in records:
            attr_name = self.attributes[record.attrid][0]
            new_attrs = self.map_attribute(attr_name, record.value.value)

            _LOGGER.debug(
                "[0x%04x:%s:0x%04x] Mapping standard %s (0x%04x) "
                "with value %s to custom %s",
                self.endpoint.device.nwk,
                self.endpoint.endpoint_id,
                self.cluster_id,
                attr_name,
                record.attrid,
                repr(record.value.value),
                repr(new_attrs),
            )

            manufacturer_attrs.update(new_attrs)

        if not manufacturer_attrs:
            return [
                [
                    foundation.WriteAttributesStatusRecord(
                        foundation.Status.FAILURE, r.attrid
                    )
                    for r in records
                ]
            ]

        await ME167ManufClusterSelf[
            self.endpoint.device.ieee
        ].endpoint.tuya_manufacturer.write_attributes(
            manufacturer_attrs, manufacturer=manufacturer
        )

        return [[foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)]]

    async def command(
        self,
        command_id: Union[foundation.Command, int, t.uint8_t],
        *args,
        manufacturer: Optional[Union[int, t.uint16_t]] = None,
        expect_reply: bool = True,
        tsn: Optional[Union[int, t.uint8_t]] = None,
    ):
        """Override the default Cluster command."""

        if command_id in (0x0000, 0x0001, 0x0002):

            if command_id == 0x0000:
                value = False
            elif command_id == 0x0001:
                value = True
            else:
                attrid = self.attributes_by_name["on_off"].id
                success, _ = await self.read_attributes(
                    (attrid,), manufacturer=manufacturer
                )
                try:
                    value = success[attrid]
                except KeyError:
                    return foundation.Status.FAILURE
                value = not value

            (res,) = await self.write_attributes(
                {"on_off": value},
                manufacturer=manufacturer,
            )
            return [command_id, res[0].status]

        return [command_id, foundation.Status.UNSUP_CLUSTER_COMMAND]


class ME167ManufCluster(TuyaManufClusterAttributes):
    """Manufacturer Specific Cluster of some thermostatic valves."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.ME167ManufCluster_bus.add_listener(self)
        global ME167ManufClusterSelf
        ME167ManufClusterSelf[self.endpoint.device.ieee] = self

    attributes = TuyaManufClusterAttributes.attributes.copy()
    attributes.update(
        {
            ME167_TEMPERATURE_ATTR: ("temperature", t.uint32_t, True),
            ME167_TARGET_TEMP_ATTR: ("target_temperature", t.uint32_t, True),
            ME167_CHILD_LOCK_ATTR: ("child_lock", t.uint8_t, True),
            ME167_MODE_ATTR: ("mode", t.uint8_t, True),
            ME167_STATE_ATTR: ("state", t.uint8_t, True),
        }
    )

    TEMPERATURE_ATTRS = {
        ME167_TEMPERATURE_ATTR: ("local_temperature", lambda value: value * 10),
        ME167_TARGET_TEMP_ATTR: (
            "occupied_heating_setpoint",
            lambda value: value * 10,
        ),
    }

    def _update_attribute(self, attrid, value):
        super()._update_attribute(attrid, value)

        if attrid in self.TEMPERATURE_ATTRS:
            self.endpoint.device.thermostat_bus.listener_event(
                "temperature_change",
                self.TEMPERATURE_ATTRS[attrid][0],
                value
                if self.TEMPERATURE_ATTRS[attrid][1] is None
                else self.TEMPERATURE_ATTRS[attrid][1](value),
            )
        elif attrid == ME167_MODE_ATTR:
            self.endpoint.device.thermostat_bus.listener_event("mode_change", value)
        elif attrid == ME167_CHILD_LOCK_ATTR:
            self.endpoint.device.ui_bus.listener_event("child_lock_change", value)
            self.endpoint.device.thermostat_onoff_bus.listener_event(
                "child_lock_change", value
            )
        elif attrid == ME167_STATE_ATTR:
            self.endpoint.device.thermostat_bus.listener_event(
                "hass_climate_state_change", value
            )


class ME167Thermostat(TuyaThermostatCluster):
    """Thermostat cluster for some thermostatic valves."""

    class Preset(t.enum8):
        """Working modes of the thermostat."""

        Away = 0x00
        Schedule = 0x01
        Manual = 0x02
        Comfort = 0x03
        Eco = 0x04
        Boost = 0x05
        Complex = 0x06

    _CONSTANT_ATTRIBUTES = {
        0x001B: Thermostat.ControlSequenceOfOperation.Heating_Only,
    }

    attributes = TuyaThermostatCluster.attributes.copy()
    attributes.update(
        {
            0x4000: ("operation_preset", Preset, True),
        }
    )

    DIRECT_MAPPING_ATTRS = {
        "occupied_heating_setpoint": (
            ME167_TARGET_TEMP_ATTR,
            lambda value: round(value / 10),
        ),
        "operation_preset": (ME167_MODE_ATTR, None),
    }

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.endpoint.device.thermostat_bus.add_listener(self)
        self.endpoint.device.thermostat_bus.listener_event(
            "temperature_change",
            "min_heat_setpoint_limit",
            ME167_MIN_TEMPERATURE_VAL * 100,
        )
        self.endpoint.device.thermostat_bus.listener_event(
            "temperature_change",
            "max_heat_setpoint_limit",
            ME167_MAX_TEMPERATURE_VAL * 100,
        )

    def map_attribute(self, attribute, value):
        """Map standardized attribute value to dict of manufacturer values."""

        if attribute in self.DIRECT_MAPPING_ATTRS:
            return {
                self.DIRECT_MAPPING_ATTRS[attribute][0]: value
                if self.DIRECT_MAPPING_ATTRS[attribute][1] is None
                else self.DIRECT_MAPPING_ATTRS[attribute][1](value)
            }

        if attribute in ("system_mode", "programing_oper_mode"):
            if attribute == "system_mode":
                system_mode = value
                oper_mode = self._attr_cache.get(
                    self.attributes_by_name["programing_oper_mode"].id,
                    self.ProgrammingOperationMode.Simple,
                )
            else:
                system_mode = self._attr_cache.get(
                    self.attributes_by_name["system_mode"].id, self.SystemMode.Heat
                )
                oper_mode = value
            if system_mode == self.SystemMode.Off:
                return {ME167_MODE_ATTR: 2}
            if system_mode == self.SystemMode.Heat:
                if oper_mode == self.ProgrammingOperationMode.Schedule_programming_mode:
                    return {ME167_MODE_ATTR: 0}
                if oper_mode == self.ProgrammingOperationMode.Simple:
                    return {ME167_MODE_ATTR: 1}
                self.error("Unsupported value for ProgrammingOperationMode")
            else:
                self.error("Unsupported value for SystemMode")

    def hass_climate_state_change(self, attrid, value):
        """Update of the HASS Climate gui state."""
        self.endpoint.device.thermostat_bus.listener_event("state_change", not value)

    def mode_change(self, value):
        """System Mode change."""
        if value == 0:
            operation_preset = self.Preset.Schedule
            prog_mode = self.ProgrammingOperationMode.Schedule_programming_mode
            occupancy = self.Occupancy.Occupied
            system_mode = self.SystemMode.Heat
        elif value == 1:
            operation_preset = self.Preset.Manual
            prog_mode = self.ProgrammingOperationMode.Simple
            occupancy = self.Occupancy.Occupied
            system_mode = self.SystemMode.Heat
        elif value == 2:
            operation_preset = self.Preset.Manual
            prog_mode = self.ProgrammingOperationMode.Simple
            occupancy = self.Occupancy.Occupied
            system_mode = self.SystemMode.Off

        self._update_attribute(self.attributes_by_name["system_mode"].id, system_mode)
        self._update_attribute(
            self.attributes_by_name["programing_oper_mode"].id, prog_mode
        )
        self._update_attribute(self.attributes_by_name["occupancy"].id, occupancy)
        self._update_attribute(
            self.attributes_by_name["operation_preset"].id, operation_preset
        )


class ME167UserInterface(TuyaUserInterfaceCluster):
    """HVAC User interface cluster for tuya electric heating thermostats."""

    _CHILD_LOCK_ATTR = ME167_CHILD_LOCK_ATTR


class ME167ChildLock(CustomTuyaOnOff):
    """On/Off cluster for the child lock function."""

    def child_lock_change(self, value):
        """Child lock change."""
        self._update_attribute(self.attributes_by_name["on_off"].id, value)

    def map_attribute(self, attribute, value):
        """Map standardized attribute value to dict of manufacturer values."""
        if attribute == "on_off":
            return {ME167_CHILD_LOCK_ATTR: value}


class ME167(TuyaThermostat):
    """ME167 Thermostatic radiator valve and clones."""

    def __init__(self, *args, **kwargs):
        """Init device."""
        self.thermostat_onoff_bus = Bus()
        self.ME167ManufCluster_bus = Bus()
        super().__init__(*args, **kwargs)

    signature = {
        #   "endpoints": {
        #     "1": {
        #       "profile_id": 260,
        #       "device_type": "0x0051",
        #       "in_clusters": [
        #         "0x0000",
        #         "0x0004",
        #         "0x0005",
        #         "0xef00"
        #       ],
        #       "out_clusters": [
        #         "0x000a",
        #         "0x0019"
        #       ]
        #     }
        #   },
        MODELS_INFO: [
            ("_TZE200_bvu2wnxz", "TS0601"),
        ],
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.SMART_PLUG,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    TuyaManufClusterAttributes.cluster_id,
                ],
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            }
        },
    }

    replacement = {
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.THERMOSTAT,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    ME167ManufCluster,
                    ME167Thermostat,
                    ME167UserInterface,
                    TuyaPowerConfigurationCluster,
                ],
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            },
            2: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [
                    ME167ChildLock,
                ],
                OUTPUT_CLUSTERS: [],
            },
        }
    }
