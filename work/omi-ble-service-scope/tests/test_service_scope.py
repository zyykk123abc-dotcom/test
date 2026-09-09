"""Offline behavioral reproduction using original Omi + Bleak lookup/dispatch.

Hardware/OS transport, characteristic records, exceptions and UUID utility imports
are fixtures. UUID fixtures use full canonical UUIDs only. No radio, account,
network, dependency installer or credentials are used. Not a hardware test.
"""
from __future__ import annotations
import asyncio
import functools
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
import types
import unittest
import uuid
from typing import Awaitable, Callable, Union
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SET = os.environ.get("SOURCE_SET", "candidate")
if SOURCE_SET not in {"upstream", "candidate"}:
    raise SystemExit("SOURCE_SET must be upstream or candidate")


def git_blob(path):
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


assert git_blob(ROOT / "upstream/omi/ble.py") == "6b434b6075682bfff9e94f5ce0c7e9b3c43ced88"
assert git_blob(ROOT / "upstream/omi/constants.py") == "aac6b07f4b69b1493e10a05e6dd750f8ab4b6247"
assert git_blob(ROOT / "vendor/service.py") == "09c503c99a8ede8f9dbf3eda9322ff32508476fd"


def module(name, **attributes):
    result = types.ModuleType(name)
    result.__dict__.update(attributes)
    sys.modules[name] = result
    return result


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


class BleakError(Exception):
    pass


class BleakCharacteristicNotFoundError(BleakError):
    pass


class Characteristic:
    def __init__(self, handle, uuid_string, service_handle):
        self.handle = handle
        self.uuid = str(uuid.UUID(uuid_string))
        self.service_handle = service_handle


module("bleak", __path__=[])
module("bleak.exc", BleakError=BleakError)
module("bleak.uuids", normalize_uuid_str=lambda s: str(uuid.UUID(s)), uuidstr_to_str=lambda s: s)
module("bleak.backends", __path__=[])
module("bleak.backends.characteristic", BleakGATTCharacteristic=Characteristic)
module("bleak.backends.descriptor", BleakGATTDescriptor=object)
services_module = load("bleak.backends.service", ROOT / "vendor/service.py")


class Service(services_module.BleakGATTService):
    def __init__(self, handle, uuid_string):
        super().__init__(None)
        self._handle = handle
        self._uuid = str(uuid.UUID(uuid_string))
        self._characteristics = []

    @property
    def handle(self):
        return self._handle

    @property
    def uuid(self):
        return self._uuid

    @property
    def characteristics(self):
        return self._characteristics

    def add_characteristic(self, characteristic):
        self._characteristics.append(characteristic)


notification_tasks = set()
namespace = dict(
    Union=Union, Awaitable=Awaitable, Callable=Callable,
    BleakGATTCharacteristic=Characteristic,
    BleakError=BleakError,
    BleakCharacteristicNotFoundError=BleakCharacteristicNotFoundError,
    uuid=uuid, asyncio=asyncio, inspect=inspect, functools=functools,
    _background_tasks=notification_tasks,
)
exec(compile((ROOT / "vendor/start_notify.py").read_text(), "vendor/start_notify.py", "exec"), namespace)


class ProbeComplete(Exception):
    """Deterministically end after notification delivery, before infinite listen."""


class TransportFixture:
    def __init__(self):
        self.handles = []

    async def start_notify(self, characteristic, callback, **kwargs):
        self.handles.append(characteristic.handle)
        callback(bytearray(b"\x01\x02\x03\x04\x05"))
        if notification_tasks:
            await asyncio.gather(*list(notification_tasks))
        raise ProbeComplete()


class ClientFixture:
    start_notify = namespace["start_notify"]

    def __init__(self, collection):
        self.services = collection
        self.is_connected = True
        self._backend = TransportFixture()
        self.exited = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.is_connected = False
        self.exited = True


sys.modules["bleak"].BleakClient = ClientFixture
sys.modules["bleak"].BleakScanner = object
module("scope_fixture_omi", __path__=[str(ROOT / SOURCE_SET / "omi")])
ble = load("scope_fixture_omi.ble", ROOT / SOURCE_SET / "omi/ble.py")
OMI = "19b10000-e8f2-537e-4f6c-d104768a1214"
CUSTOM = "aabbccdd-0000-1000-8000-00805f9b34fb"
MISSING = "aabbccde-0000-1000-8000-00805f9b34fb"
AUDIO = "19b10001-e8f2-537e-4f6c-d104768a1214"


def collection(*layouts):
    out = services_module.BleakGATTServiceCollection()
    for handle, service_id, chars in layouts:
        out.add_service(Service(handle, service_id))
        for char_handle, char_id in chars:
            out.add_characteristic(Characteristic(char_handle, char_id, handle))
    return out


class ServiceScopeTests(unittest.IsolatedAsyncioTestCase):
    async def run_probe(self, services, callback, *, expected=ProbeComplete, payload=False, **kwargs):
        client = ClientFixture(services)
        with patch.object(ble, "BleakClient", return_value=client):
            try:
                with self.assertRaises(expected):
                    fn = ble.listen_payload if payload else ble.listen
                    await fn("fixture-device", callback, **kwargs)
            finally:
                self.assertTrue(client.exited, "connection context must be exited")
        return client

    async def test_default_service_sync_callback(self):
        packets = []
        c = await self.run_probe(collection((1, OMI, [(11, AUDIO)])), packets.append)
        self.assertEqual(c._backend.handles, [11])
        self.assertEqual(packets, [b"\x01\x02\x03\x04\x05"])
        self.assertIs(type(packets[0]), bytes)

    async def test_explicit_service_disambiguates_duplicate_characteristic_uuid(self):
        packets = []
        c = await self.run_probe(collection((1, OMI, [(11, AUDIO)]), (2, CUSTOM, [(21, AUDIO)])),
                                 packets.append, service_uuid=CUSTOM)
        self.assertEqual(c._backend.handles, [21])
        self.assertEqual(len(packets), 1)

    async def test_missing_service_does_not_subscribe_to_another_service(self):
        packets = []
        c = await self.run_probe(collection((1, OMI, [(11, AUDIO)])), packets.append,
                                 service_uuid=MISSING, expected=BleakError)
        self.assertEqual(c._backend.handles, [])
        self.assertEqual(packets, [])

    async def test_characteristic_only_in_other_service_is_rejected(self):
        packets = []
        c = await self.run_probe(collection((1, OMI, [(11, AUDIO)]), (2, CUSTOM, [])), packets.append,
                                 service_uuid=CUSTOM, expected=BleakError)
        self.assertEqual(c._backend.handles, [])
        self.assertEqual(packets, [])

    async def test_async_callback_is_awaited(self):
        packets = []
        async def callback(packet):
            packets.append(packet)
        c = await self.run_probe(collection((1, OMI, [(11, AUDIO)])), callback)
        self.assertEqual(c._backend.handles, [11])
        self.assertEqual(packets, [b"\x01\x02\x03\x04\x05"])

    async def test_explicit_uppercase_service_uuid(self):
        packets = []
        c = await self.run_probe(collection((2, CUSTOM, [(21, AUDIO)])), packets.append,
                                 service_uuid=CUSTOM.upper())
        self.assertEqual(c._backend.handles, [21])

    async def test_payload_wrapper_preserves_header_stripping(self):
        packets = []
        c = await self.run_probe(collection((1, OMI, [(11, AUDIO)])), packets.append, payload=True)
        self.assertEqual(c._backend.handles, [11])
        self.assertEqual(packets, [b"\x04\x05"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ServiceScopeTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"source_set": SOURCE_SET, "tests_run": result.testsRun,
                      "failures": len(result.failures), "errors": len(result.errors),
                      "passed": result.testsRun - len(result.failures) - len(result.errors),
                      "hardware_tested": False, "full_sdk_suite": False,
                      "complete_repository_preflight": False}, sort_keys=True))
    sys.exit(not result.wasSuccessful())
