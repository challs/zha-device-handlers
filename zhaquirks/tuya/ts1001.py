"""Tuya 4 Button Remote."""

from typing import Any, List, Optional, Tuple, Union

from zhaquirks import GroupBoundCluster
from zigpy.profiles import zha
from zigpy.quirks import CustomDevice, CustomCluster
import zigpy.types as t
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import Basic, Identify, LevelControl, OnOff, Ota, PowerConfiguration, Scenes, Time, Groups
from zigpy.zcl.clusters.lightlink import LightLink

from zhaquirks.const import (
    ARGS,
    COMMAND_MOVE,
    COMMAND_STEP,
    COMMAND_STOP,
    LONG_RELEASE,
    TURN_ON,
    TURN_OFF,
    DIM_UP,
    DIM_DOWN,
    COMMAND,
    DEVICE_TYPE,
    DOUBLE_PRESS,
    ENDPOINT_ID,
    CLUSTER_ID,
    ENDPOINTS,
    INPUT_CLUSTERS,
    LONG_PRESS,
    MODEL,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
    SHORT_PRESS,
    ZHA_SEND_EVENT,
)
from zhaquirks.tuya import TuyaManufClusterAttributes, TuyaOnOff, TuyaSmartRemoteOnOffCluster, TuyaSwitch, TuyaNewManufCluster

class TuyaRemote1001OnOffCluster(CustomCluster):

    press_type = {
        0x00: SHORT_PRESS,
        0x01: SHORT_PRESS,
        0x02: LONG_PRESS,
    }

    name = "TS1001_cluster"
    ep_attribute = "TS1001_cluster"
    cluster_id = 6

    def handle_cluster_request(
        self,
        hdr: foundation.ZCLHeader,
        args: Tuple,
        *,
        dst_addressing: Optional[
            Union[t.Addressing.Group, t.Addressing.IEEE, t.Addressing.NWK]
        ] = None,
    ) -> None:
        """Handle cluster request."""
        if hdr.command_id not in (0x0001, 0x0002):
            return super().handle_cluster_request(
                hdr, args, dst_addressing=dst_addressing
            )

        # Send default response because the MCU expects it
        if not hdr.frame_control.disable_default_response:
            self.send_default_rsp(hdr, status=foundation.Status.SUCCESS)

    def handle_cluster_request_old(
        self,
        hdr: foundation.ZCLHeader,
        args: List[Any],
        *,
        dst_addressing: Optional[
            Union[t.Addressing.Group, t.Addressing.IEEE, t.Addressing.NWK]
        ] = None,
    ):
        prev_tsn = self.last_tsn
        super().handle_cluster_request(hdr, args=args, dst_addressing=dst_addressing)

        if self.last_tsn == prev_tsn:
            # No command was processed
            return
        if hdr.command_id == 0x02:
            press_type = args[0]
            self.listener_event(
                #ZHA_SEND_EVENT, self.press_type.get(press_type, "unknown"), []
                # Still need to work out different press types
                ZHA_SEND_EVENT, "remote_button_short_press", []
            )

class TuyaRemote1001OnOffClusterX(TuyaSmartRemoteOnOffCluster):
    """Remote switch handler. Press type argument is 1 for short presses"""
    press_type = {
        0x01: SHORT_PRESS,
    }
    name = "TS1001_cluster"
    ep_attribute = "TS1001_cluster"

class TuyaDimRemote1001(CustomDevice):
    """Tuya 4-button remote device."""

    signature = {
        # SizePrefixedSimpleDescriptor(endpoint=1, profile=260, device_type=260, device_version=1, input_clusters=[0, 1, 3, 4, 4096],
        # output_clusters=[25, 10, 3, 4, 5, 6, 8, 4096]
        MODEL: "TS1001",
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.DIMMER_SWITCH,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    PowerConfiguration.cluster_id,
                    Identify.cluster_id,
                    Groups.cluster_id,
                    LightLink.cluster_id,
                ],
                OUTPUT_CLUSTERS: [
                    Identify.cluster_id,
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    OnOff.cluster_id,
                    LevelControl.cluster_id,
                    Time.cluster_id,
                    Ota.cluster_id,
                    LightLink.cluster_id,
                ],
            },
        },
    }
    replacement = {
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.REMOTE_CONTROL,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    PowerConfiguration.cluster_id,
                    Identify.cluster_id,
                    Groups.cluster_id , # Groups.cluster_id,
                    LightLink.cluster_id,
                ],
                OUTPUT_CLUSTERS: [
                    Identify.cluster_id,
                    Groups.cluster_id, #                    TuyaRemote1001OnOffCluster,
                    Scenes.cluster_id,
                    #TuyaRemote1001OnOffCluster,
                    TuyaSmartRemoteOnOffCluster,
                    LevelControl.cluster_id,
                    Time.cluster_id,
                    Ota.cluster_id,
                    LightLink.cluster_id,
                ],
            },
        },
    }
    device_automation_triggers = {
        (SHORT_PRESS, TURN_ON): {CLUSTER_ID: 6, COMMAND: TURN_ON},
        (SHORT_PRESS, TURN_ON): {CLUSTER_ID: 6, COMMAND: TURN_ON},
        (SHORT_PRESS, TURN_OFF): {CLUSTER_ID: 6, COMMAND: TURN_OFF},
        (SHORT_PRESS, DIM_DOWN): {CLUSTER_ID: 8, COMMAND: COMMAND_STEP, ARGS: [1, 51, 10]},
        (LONG_PRESS, DIM_DOWN): {CLUSTER_ID: 8, COMMAND: COMMAND_MOVE, ARGS: [1, 51]},
        (LONG_RELEASE, DIM_DOWN): {CLUSTER_ID: 8, COMMAND: COMMAND_STOP},
        (SHORT_PRESS, DIM_UP): {CLUSTER_ID: 8, COMMAND: COMMAND_STEP, ARGS: [0, 51, 10]},
        (LONG_PRESS, DIM_UP): {CLUSTER_ID: 8, COMMAND: COMMAND_MOVE, ARGS: [0, 51]},

    }

# ON Button
# [bellows.uart] Data frame: b'631bb157546f15b658924a24ab5593499cf0e767ca0b9874f9c77f74fc7c40447e'
# [bellows.uart] Sending: b'87009f7e'
# [bellows.ezsp.protocol] Application frame 69 (incomingMessageHandler) received: b'0004010600010100010000bec0cc27c5ffff04011cfd0002'
# [bellows.zigbee.application] Received incomingMessageHandler frame with [<EmberIncomingMessageType.INCOMING_UNICAST: 0>, EmberApsFrame(profileId=260, clusterId=6, sourceEndpoint=1, destinationEndpoint=1, options=<EmberApsOption.APS_OPTION_ENABLE_ROUTE_DISCOVERY: 256>, groupId=0, sequence=190), 192, -52, 0xc527, 255, 255, b'\x01\x1c\xfd\x00']
# [zigpy.zcl] [0xc527:1:0x0006] ZCL deserialize: <ZCLHeader frame_control=<FrameControl frame_type=CLUSTER_COMMAND manufacturer_specific=False is_reply=False disable_default_response=False> manufacturer=None tsn=28 command_id=253>
# [zigpy.zcl] [0xc527:1:0x0006] Unknown cluster-specific command 253
# [zigpy.zcl] [0xc527:1:0x0006] ZCL request 0x00fd: b'\x00'
# [zigpy.zcl] [0xc527:1:0x0006] No handler for cluster command 253

# OFF button
# [bellows.zigbee.application] Received incomingMessageHandler frame with [<EmberIncomingMessageType.INCOMING_UNICAST: 0>, EmberApsFrame(profileId=260, clusterId=4, sourceEndpoint=1, destinationEndpoint=1, options=<EmberApsOption.APS_OPTION_ENABLE_ROUTE_DISCOVERY|APS_OPTION_RETRY: 320>, groupId=0, sequence=193), 168, -58, 0xc527, 255, 255, b'\x19\xde\x02\xff\x00']
# [zigpy.zcl] [0xc527:1:0x0004] ZCL deserialize: <ZCLHeader frame_control=<FrameControl frame_type=CLUSTER_COMMAND manufacturer_specific=False is_reply=True disable_default_response=True> manufacturer=None tsn=222 command_id=2>
# [zigpy.zcl] [0xc527:1:0x0004] ZCL request 0x0002: [255, []]
# [zigpy.zcl] [0xc527:1:0x0004] No handler for cluster command 2

# [zigpy_znp.api] Sending request: AF.DataRequestSrcRtg.Req(DstAddr=0xF33D, DstEndpoint=1, SrcEndpoint=1, ClusterId=6, TSN=125, Options=<TransmitOptions.SUPPRESS_ROUTE_DISC_NETWORK: 32>, Radius=30, SourceRoute=[], Data=b'\x18\x7D\x0B\x00\x00')

# Dim down button
# [bellows.ezsp.protocol] Application frame 84 (customFrameHandler) received: b'1200100c00000800040101be01030201330a00'
# [bellows.zigbee.application] Received customFrameHandler frame with [b'\x00\x10\x0c\x00\x00\x08\x00\x04\x01\x01\xbe\x01\x03\x02\x013\n\x00']

# Dim down (step)
# [zigpy_znp.api] Received command: AF.IncomingMsg.Callback(GroupId=0x0000, ClusterId=8, SrcAddr=0xF33D, SrcEndpoint=1, DstEndpoint=1, WasBroadcast=<Bool.false: 0>, LQI=117, SecurityUse=<Bool.false: 0>, TimeStamp=3844767, TSN=0, Data=b'\x01\x64\x02\x01\x33\x0A\x00', MacSrcAddr=0xF33D, MsgResultRadius=11)
# [zigpy.zcl] [0xf33d:1:0x0008] ZCL deserialize: <ZCLHeader frame_control=<FrameControl frame_type=CLUSTER_COMMAND manufacturer_specific=False is_reply=False disable_default_response=False> manufacturer=None tsn=100 command_id=2>
# [zigpy.zcl] [0xf33d:1:0x0008] ZCL request 0x0002: [1, 51, 10]
# [zigpy.zcl] [0xf33d:1:0x0008] No handler for cluster command 2
# [homeassistant.core] Bus:Handling <Event zha_event[L]: device_ieee=bc:33:ac:ff:fe:fe:01:95, unique_id=bc:33:ac:ff:fe:fe:01:95:1:0x0008, device_id=d2a83b6f9ef3689cb2e5a51021dfbd9a, endpoint_id=1, cluster_id=8, command=step, args=[1, 51, 10]>

# Dim up
# [bellows.zigbee.application] Received messageSentHandler frame with [<EmberOutgoingMessageType.OUTGOING_MULTICAST: 3>, 65533, EmberApsFrame(profileId=260, clusterId=8, sourceEndpoint=1, destinationEndpoint=255, options=<EmberApsOption.APS_OPTION_ENABLE_ROUTE_DISCOVERY: 256>, groupId=0, sequence=63), 0, <EmberStatus.SUCCESS: 0>, b'']


# OFF button 16/01/22

# [bellows.zigbee.application] Received incomingMessageHandler frame with [<EmberIncomingMessageType.INCOMING_UNICAST: 0>, EmberApsFrame(profileId=260, clusterId=1026, sourceEndpoint=1, destinationEndpoint=1, options=<EmberApsOption.APS_OPTION_ENABLE_ROUTE_DISCOVERY: 256>, groupId=0, sequence=192), 172, -57, 0xaf97, 255, 255, b'\x18\xd5\n\x00\x00)\x8d\x08']
# [zigpy.zcl] [0xaf97:1:0x0402] ZCL deserialize: <ZCLHeader frame_control=<FrameControl frame_type=GLOBAL_COMMAND manufacturer_specific=False is_reply=True disable_default_response=True> manufacturer=None tsn=213 command_id=Command.Report_Attributes>
# [zigpy.zcl] [0xaf97:1:0x0402] ZCL request 0x000a: [[Attribute(attrid=0, value=<TypeValue type=int16s, value=2189>)]]
# [zigpy.zcl] [0xaf97:1:0x0402] Attribute report received: measured_value=2189
# [bellows.zigbee.application] Received messageSentHandler frame with [<EmberOutgoingMessageType.OUTGOING_MULTICAST: 3>, 65533, EmberApsFrame(profileId=260, clusterId=6, sourceEndpoint=1, destinationEndpoint=255, options=<EmberApsOption.APS_OPTION_ENABLE_ROUTE_DISCOVERY: 256>, groupId=0, sequence=130), 0, <EmberStatus.SUCCESS: 0>, b'']
# [bellows.zigbee.application] Unexpected message send notification tag: 0
