"""Fixtures for all tests."""

from asynctest import CoroutineMock
import pytest
from typing import Literal, Union

import zigpy.application
import zigpy.device
import zigpy.types
import zigpy.zcl.foundation as foundation
import zigpy.quirks

from zhaquirks.const import (
    DEVICE_TYPE,
    ENDPOINTS,
    INPUT_CLUSTERS,
    MANUFACTURER,
    MODEL,
    MODELS_INFO,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
)


class MockApp(zigpy.application.ControllerApplication):
    """App Controller."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self._ieee = zigpy.types.EUI64(b"Zigbee78")
        self._nwk = zigpy.types.NWK(0x0000)

    async def probe(self, *args):
        """Probe method."""
        return True

    async def shutdown(self):
        """Mock shutdown."""

    async def startup(self, *args):
        """Mock startup."""

    async def permit_ncp(self, *args):
        """Mock permit ncp."""

    mrequest = CoroutineMock()
    request = CoroutineMock(return_value=(foundation.Status.SUCCESS, None))


@pytest.fixture(name="MockAppController")
def app_controller_mock():
    """App controller mock."""
    config = {"device": {"path": "/dev/ttyUSB0"}, "database": None}
    config = MockApp.SCHEMA(config)
    app = MockApp(config)
    return app


@pytest.fixture
def ieee_mock():
    """Return a static ieee."""
    return zigpy.types.EUI64([1, 2, 3, 4, 5, 6, 7, 8])


@pytest.fixture
def zigpy_device_mock(MockAppController, ieee_mock):
    """Zigpy device mock."""

    def _dev(ieee=None, nwk=zigpy.types.NWK(0x1234)):
        if ieee is None:
            ieee = ieee_mock
        device = MockAppController.add_device(ieee, nwk)
        return device

    return _dev


@pytest.fixture
def zigpy_device_from_quirk(MockAppController, ieee_mock):
    """Create zigpy device from Quirk's signature."""

    def _dev(quirk, ieee=None, nwk=zigpy.types.NWK(0x1234), apply_quirk=True):
        if ieee is None:
            ieee = ieee_mock
        models_info = quirk.signature.get(
            MODELS_INFO,
            (
                (
                    quirk.signature.get(MANUFACTURER, "Mock Manufacturer"),
                    quirk.signature.get(MODEL, "Mock Model"),
                ),
            ),
        )
        manufacturer, model = models_info[0]

        raw_device = zigpy.device.Device(MockAppController, ieee, nwk)
        raw_device.manufacturer = manufacturer
        raw_device.model = model

        endpoints = quirk.signature.get(ENDPOINTS, {})
        for ep_id, ep_data in endpoints.items():
            ep = raw_device.add_endpoint(ep_id)
            ep.profile_id = ep_data.get(PROFILE_ID, 0x0260)
            ep.device_type = ep_data.get(DEVICE_TYPE, 0xFEDB)
            in_clusters = ep_data.get(INPUT_CLUSTERS, [])
            for cluster_id in in_clusters:
                ep.add_input_cluster(cluster_id)
            out_clusters = ep_data.get(OUTPUT_CLUSTERS, [])
            for cluster_id in out_clusters:
                ep.add_output_cluster(cluster_id)

        if not apply_quirk:
            return raw_device

        device = quirk(MockAppController, ieee, nwk, raw_device)
        MockAppController.devices[ieee] = device

        return device

    return _dev

@pytest.fixture
def assert_signature_matches_quirk():
    """Return a function that can be used to check if a given quirk matches a signature"""
    def _check(quirk, signature):
        # Check device signature as copied from Zigbee device signature window for the device
        class FakeDevEndpoint:
            def __init__(self, endpoint):
                self.endpoint = endpoint
            def __getattr__(self, key):
                if key == "device_type":
                    return int(self.endpoint[key], 16)
                elif key in ("in_clusters", "out_clusters"):
                    return [
                        int(cluster_id, 16)
                        for cluster_id in self.endpoint[key]
                    ]
                else:
                    return self.endpoint[key]

        class FakeDevice:
            nwk = 0

            def __init__(self, signature):
                self.endpoints = {
                    int(id): FakeDevEndpoint(ep)
                    for id, ep in signature["endpoints"].items()
                }
                for attr in ("manufacturer", "model", "ieee"):
                    setattr(self, attr, signature.get(attr))

            def __getitem__(self, key):
                # Return item from signature, or None if not given
                return self.endpoints.get(key)
            def __getattr__(self, key):
                # Return item from signature, or None if not given
                return self.endpoints.get(key)

        test_dev = FakeDevice(signature)
        device = zigpy.quirks.get_device(test_dev)
        assert isinstance(device, quirk)
    return _check

@pytest.fixture
def input_cluster(zigpy_device_from_quirk):
    """
    Return a function which can create a test device with the given input cluster
    """
    def _input_cluster(quirk, endpoint: int, cluster: str) -> zigpy.quirks.CustomCluster:
        # Create test device for the quirk
        device: zigpy.quirks.CustomDevice = zigpy_device_from_quirk(quirk)

        # The cluster we wish to test
        cluster = getattr(device[endpoint], cluster)

        return cluster

    return _input_cluster

@pytest.fixture
def output_cluster(zigpy_device_from_quirk):
    """
    Return a function which can create a test device with the given output cluster
    """
    def _output_cluster(quirk, endpoint: int, cluster_id: int) -> zigpy.quirks.CustomCluster:
        # Create test device for the quirk
        device: zigpy.quirks.CustomDevice = zigpy_device_from_quirk(quirk)

        # The cluster we wish to test
        cluster = device.endpoints[endpoint].out_clusters[cluster_id]
        return cluster

    return _output_cluster

@pytest.fixture
def verify_event(zigpy_device_from_quirk, input_cluster):
    """
    Check that a quick generates an event from a given message

    This provides a function which can be called to check that a message
    sent to a quirk causes the given event to be sent.
    """
    def _verify(cluster: zigpy.quirks.CustomCluster, message: list[Literal], event_command: str, event_args: Union[int, dict]):
        class EventChecker:
            """
            Class that listens an incoming zha event and checks its contents
            """
            event_received = False
            def zha_send_event(self, command: str, args: Union[int, dict]):
                assert command == event_command, f"Event error: expected command {event_command} but received {command}"
                assert args == event_args, f"Event error: expected args {event_args} but received {args}"
                assert not self.event_received, "Duplicate event received"
                self.event_received = True

        listener = EventChecker()
        cluster.add_listener(listener)

        # Generate a message and pass to the cluster to handle
        hdr, args = cluster.deserialize(message)
        cluster.handle_message(hdr, args)

        # Check that the listener received a valid event
        assert listener.event_received

    return _verify
