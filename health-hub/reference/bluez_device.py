"""Read-only resolution of already-known BLE devices through BlueZ.

BlueZ may stop advertising a paired or currently connected sensor.  In that
case a scan-only lookup can time out even though the device is present in the
system object manager.  This helper reads that inventory without pairing,
disconnecting, or changing adapter state; callers can fall back to their
normal Bleak address discovery when it returns ``None``.
"""
from __future__ import annotations

import sys
from typing import Any, Callable, Mapping


DEVICE_IFACE = "org.bluez.Device1"


def _unwrap(value: Any) -> Any:
    """Unwrap dbus-fast Variants, including values nested in containers."""
    if hasattr(value, "value") and hasattr(value, "signature"):
        return _unwrap(value.value)
    if isinstance(value, Mapping):
        return {key: _unwrap(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unwrap(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_unwrap(item) for item in value)
    return value


def select_paired_or_connected_device(
    objects: Mapping[str, Mapping[str, Mapping[str, Any]]], address: str
) -> tuple[str, dict[str, Any]] | None:
    """Select the exact paired/connected BlueZ object for ``address``.

    The address comparison is case-insensitive.  Unknown addresses and
    unpaired/disconnected stale objects are deliberately rejected.
    """
    wanted = address.strip().lower()
    if not wanted:
        return None
    for path, interfaces in objects.items():
        raw = interfaces.get(DEVICE_IFACE)
        if not isinstance(raw, Mapping):
            continue
        props = _unwrap(raw)
        if str(props.get("Address", "")).lower() != wanted:
            continue
        if props.get("Paired") is True or props.get("Connected") is True:
            return str(path), dict(props)
    return None


async def resolve_existing_device(
    address: str,
    *,
    bus_factory: Callable[[], Any] | None = None,
    device_cls: type | None = None,
) -> Any | None:
    """Return a Bleak ``BLEDevice`` from BlueZ's existing object inventory.

    This is Linux-only and read-only.  Importing on other platforms or any
    D-Bus/import/lookup failure returns ``None`` so normal Bleak discovery can
    be attempted by the caller.  ``bus_factory`` and ``device_cls`` are test
    seams and are not needed in production.
    """
    if sys.platform != "linux":
        return None
    bus = None
    try:
        if bus_factory is None:
            from dbus_fast.aio import MessageBus
            from dbus_fast import BusType

            bus_factory = lambda: MessageBus(bus_type=BusType.SYSTEM)
        if device_cls is None:
            from bleak.backends.device import BLEDevice

            device_cls = BLEDevice
        bus = bus_factory()
        await bus.connect()
        introspection = await bus.introspect("org.bluez", "/")
        proxy = bus.get_proxy_object("org.bluez", "/", introspection)
        manager = proxy.get_interface("org.freedesktop.DBus.ObjectManager")
        objects = await manager.call_get_managed_objects()
        selected = select_paired_or_connected_device(objects, address)
        if selected is None:
            return None
        path, props = selected
        name = str(props.get("Name") or props.get("Alias") or address)
        details = {"path": path, "props": props}
        # Bleak 2.1.x takes address/name/details (in that order). Keywords
        # keep this correct across the backend's positional-signature change.
        return device_cls(address=address, name=name, details=details)
    except Exception:
        return None
    finally:
        if bus is not None:
            try:
                bus.disconnect()
            except Exception:
                pass
