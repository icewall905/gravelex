import asyncio
import pytest

import bluez_device


class Variant:
    signature = "v"

    def __init__(self, value):
        self.value = value


class FakeDevice:
    def __init__(self, *, address, name, details):
        self.name, self.address = name, address
        self.details = details


class Manager:
    def __init__(self, objects=None, error=None):
        self.objects, self.error = objects, error

    async def call_get_managed_objects(self):
        if self.error:
            raise self.error
        return self.objects


class Proxy:
    def __init__(self, manager):
        self.manager = manager

    def get_interface(self, name):
        assert name == "org.freedesktop.DBus.ObjectManager"
        return self.manager


class Bus:
    def __init__(self, manager):
        self.manager, self.disconnected = manager, False

    async def connect(self):
        return None

    async def introspect(self, service, path):
        assert (service, path) == ("org.bluez", "/")
        return object()

    def get_proxy_object(self, service, path, introspection):
        return Proxy(self.manager)

    def disconnect(self):
        self.disconnected = True


def device_objects(*, address="AA:BB:CC:DD:EE:FF", paired=True, connected=False):
    return {
        "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF": {
            "org.bluez.Device1": {
                "Address": Variant(address),
                "Name": Variant("HRM-Pro Plus"),
                "Paired": Variant(paired),
                "Connected": Variant(connected),
                "UUIDs": Variant(["0000180d-0000-1000-8000-00805f9b34fb"]),
            }
        }
    }


def test_select_unwraps_variants_and_requires_paired_or_connected():
    selected = bluez_device.select_paired_or_connected_device(device_objects(), "aa:bb:cc:dd:ee:ff")
    assert selected[0].endswith("dev_AA_BB_CC_DD_EE_FF")
    assert selected[1]["Name"] == "HRM-Pro Plus"
    assert selected[1]["UUIDs"] == ["0000180d-0000-1000-8000-00805f9b34fb"]
    assert bluez_device.select_paired_or_connected_device(device_objects(paired=False), "AA:BB:CC:DD:EE:FF") is None


def test_non_linux_returns_none_without_importing_dbus(monkeypatch):
    monkeypatch.setattr(bluez_device.sys, "platform", "darwin")
    import asyncio

    assert asyncio.run(bluez_device.resolve_existing_device("AA:BB:CC:DD:EE:FF")) is None


def test_resolver_uses_actual_path_and_disconnects_bus():
    bus = Bus(Manager(device_objects(connected=True)))
    result = asyncio.run(bluez_device.resolve_existing_device(
        "AA:BB:CC:DD:EE:FF", bus_factory=lambda: bus, device_cls=FakeDevice
    ))
    assert result.details["path"].endswith("dev_AA_BB_CC_DD_EE_FF")
    assert result.details["props"]["Connected"] is True
    assert result.address == "AA:BB:CC:DD:EE:FF"
    assert result.name == "HRM-Pro Plus"
    assert bus.disconnected


def test_unknown_address_does_not_return_stale_object_and_cleans_up():
    bus = Bus(Manager(device_objects()))
    result = asyncio.run(bluez_device.resolve_existing_device(
        "11:22:33:44:55:66", bus_factory=lambda: bus, device_cls=FakeDevice
    ))
    assert result is None
    assert bus.disconnected


def test_dbus_error_returns_none_and_disconnects():
    bus = Bus(Manager(error=RuntimeError("object manager unavailable")))
    result = asyncio.run(bluez_device.resolve_existing_device(
        "AA:BB:CC:DD:EE:FF", bus_factory=lambda: bus, device_cls=FakeDevice
    ))
    assert result is None
    assert bus.disconnected
