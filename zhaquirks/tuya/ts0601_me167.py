"""Quirks for the me167 TRV"""
import logging

from zigpy.profiles import zha
import zigpy.types as t
from zigpy.zcl.clusters.general import Basic, Groups, Ota, Scenes, Time

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
    TuyaPowerConfigurationCluster2AA,
    TuyaThermostat,
    TuyaThermostatCluster,
    TuyaUserInterfaceCluster,
)

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


ME167_TARGET_TEMP_ATTR = 0x0204  # [0, 0, 0, 190] target room temp (decidegree)
ME167_TEMPERATURE_ATTR = 0x0205  # [0, 0, 0, 210] current room temp (decidegree)
ME167_MODE_ATTR = 0x0402  # [0] auto [1] heat [2] off
ME167_RUNNING_MODE_ATTR = 0x0403  # [1] idle [0] heating /!\ inverted
ME167_CHILD_LOCK_ATTR = 0x0107  # [0] unlocked [1] child-locked

ME167_MIN_TEMPERATURE_VAL = 5  # degrees
ME167_MAX_TEMPERATURE_VAL = 35  # degrees

_LOGGER = logging.getLogger(__name__)


class ME167ManufCluster(TuyaManufClusterAttributes):
    """Manufacturer Specific Cluster of some electric heating thermostats."""

    attributes = {
        ME167_TARGET_TEMP_ATTR: ("target_temperature", t.uint32_t, True),
        ME167_TEMPERATURE_ATTR: ("temperature", t.uint32_t, True),
        ME167_MODE_ATTR: ("mode", t.uint8_t, True),
        ME167_RUNNING_MODE_ATTR: ("running_mode", t.uint8_t, True),
        ME167_CHILD_LOCK_ATTR: ("child_lock", t.uint8_t, True),
    }

    def _update_attribute(self, attrid, value):
        """Process incoming events from the TRV"""
        super()._update_attribute(attrid, value)
        if attrid == ME167_TARGET_TEMP_ATTR:
            self.endpoint.device.thermostat_bus.listener_event(
                "temperature_change",
                "occupied_heating_setpoint",
                value * 10,  # decidegree to centidegree
            )
        elif attrid == ME167_TEMPERATURE_ATTR:
            self.endpoint.device.thermostat_bus.listener_event(
                "temperature_change",
                "local_temperature",
                value * 10,  # decidegree to centidegree
            )
        elif attrid == ME167_MODE_ATTR:
            self.endpoint.device.thermostat_bus.listener_event("mode_change", value)
        elif attrid == ME167_RUNNING_MODE_ATTR:
            # value is inverted
            self.endpoint.device.thermostat_bus.listener_event(
                "state_change", 1 - value
            )
        elif attrid == ME167_CHILD_LOCK_ATTR:
            self.endpoint.device.ui_bus.listener_event("child_lock_change", value)


class ME167Thermostat(TuyaThermostatCluster):
    """Thermostat cluster for some electric heating controllers."""

    _CONSTANT_ATTRIBUTES = {
        "min_heat_setpoint_limit": ME167_MIN_TEMPERATURE_VAL * 100,
        "max_heat_setpoint_limit": ME167_MAX_TEMPERATURE_VAL * 100,
    }

    class Preset(t.enum8):
        """Working modes of the thermostat."""

        Away = 0x00
        Schedule = 0x01
        Manual = 0x02

    #    self.endpoint.device.thermostat_bus.listener_event(
    #         "temperature_change",
    #         "min_heat_setpoint_limit",
    #         SITERWELL_MIN_TEMPERATURE_VAL * 100,
    #     )
    #     self.endpoint.device.thermostat_bus.listener_event(
    #         "temperature_change",
    #         "max_heat_setpoint_limit",
    #         SITERWELL_MAX_TEMPERATURE_VAL * 100,
    #     )

    def map_attribute(self, attribute, value):
        """Map standardized attribute value to dict of manufacturer values."""

        if attribute == "occupied_heating_setpoint":
            # centidegree to decidegree
            return {ME167_TARGET_TEMP_ATTR: round(value / 10)}
        # if attribute == "system_mode":
        #     if value == self.SystemMode.Off:
        #         return {ME167_ENABLED_ATTR: 0}
        #     if value == self.SystemMode.Heat:
        #         return {ME167_ENABLED_ATTR: 1}
        #     self.error("Unsupported value for SystemMode")
        # elif attribute == "programing_oper_mode":
        #     # values are inverted
        #     if value == self.ProgrammingOperationMode.Simple:
        #         return {ME167_MANUAL_MODE_ATTR: 0, ME167_SCHEDULE_MODE_ATTR: 1}
        #     if value == self.ProgrammingOperationMode.Schedule_programming_mode:
        #         return {ME167_MANUAL_MODE_ATTR: 1, ME167_SCHEDULE_MODE_ATTR: 0}
        #     self.error("Unsupported value for ProgrammingOperationMode")

        return super().map_attribute(attribute, value)

    def mode_change(self, mode):
        """
        Mode change update from device

        [0] auto [1] heat [2] off
        """
        if mode == 0:
            prog_mode = self.ProgrammingOperationMode.Schedule_programming_mode
        else:
            prog_mode = self.ProgrammingOperationMode.Simple

        self._update_attribute(
            self.attributes_by_name["programing_oper_mode"].id, prog_mode
        )

        if mode == 2:
            system_mode = self.SystemMode.Off
        else:
            system_mode = self.SystemMode.Heat
        self._update_attribute(self.attributes_by_name["system_mode"].id, system_mode)


class ME167UserInterface(TuyaUserInterfaceCluster):
    """HVAC User interface cluster for tuya electric heating thermostats."""

    _CHILD_LOCK_ATTR = ME167_CHILD_LOCK_ATTR


class ME167(TuyaThermostat):
    """Tuya thermostat for Avatto / MYUET ME167"""

    signature = {
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
                    TuyaPowerConfigurationCluster2AA,
                ],
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            }
        }
    }
