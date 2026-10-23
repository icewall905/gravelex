import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import capture


PACKET = bytes([16, 60, 0, 4])


class FakeClient:
    mode = "full"
    stop_error = None

    def __init__(self, device, **kwargs):
        self.device = device
        self.is_connected = True
        self.callback = None
        self.disconnected_callback = kwargs.get("disconnected_callback")

    async def __aenter__(self):
        if self.mode == "connect_error":
            raise OSError("connect failed")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.is_connected = False

    async def start_notify(self, characteristic, callback, **kwargs):
        FakeClient.notify_options = kwargs
        self.callback = callback
        callback(characteristic, PACKET)
        if self.mode == "early_disconnect":
            asyncio.get_running_loop().call_soon(self.disconnected_callback, self)

    async def stop_notify(self, characteristic):
        if self.stop_error:
            raise self.stop_error


async def fake_resolve(_address):
    return None


def install_fake_bleak(monkeypatch):
    monkeypatch.setitem(sys.modules, "bleak", SimpleNamespace(BleakClient=FakeClient, BleakScanner=None))
    monkeypatch.setattr(capture, "resolve_existing_device", fake_resolve)


def summary(path: Path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    return next(row for row in rows if row.get("type") == "summary")


def run_capture(monkeypatch, tmp_path, mode, stop_error=None):
    install_fake_bleak(monkeypatch)
    FakeClient.mode = mode
    FakeClient.stop_error = stop_error
    output = tmp_path / f"{mode}.jsonl"
    args = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", output=output, label="other", duration=0.01, scan=False)
    with pytest.raises(SystemExit):
        asyncio.run(capture.run(args))
    return summary(output)


def test_full_window_stop_notify_eof_is_completed_but_transport_error(monkeypatch, tmp_path):
    summary_row = run_capture(monkeypatch, tmp_path, "full", EOFError("watch closed"))
    assert summary_row["recording_completed"] is True
    assert summary_row["error_stage"] == "stop_notify"
    assert summary_row["notification_window_seconds"] >= 0.01
    assert summary_row["qualified_reference"] is False
    assert summary_row["stages"][:4] == ["connect", "subscribe", "record", "completed"]


def test_early_disconnect_is_not_completed(monkeypatch, tmp_path):
    summary_row = run_capture(monkeypatch, tmp_path, "early_disconnect")
    assert summary_row["recording_completed"] is False
    assert summary_row["error_stage"] == "record"


def test_connect_error_is_not_completed(monkeypatch, tmp_path):
    summary_row = run_capture(monkeypatch, tmp_path, "connect_error")
    assert summary_row["recording_completed"] is False
    assert summary_row["error_stage"] == "connect"


@pytest.mark.parametrize('platform,options',[('linux',{'bluez':{'use_start_notify':True}}),('darwin',{})])
def test_normal_recording_uses_platform_notification_mode(monkeypatch,tmp_path,platform,options):
    install_fake_bleak(monkeypatch)
    monkeypatch.setattr(capture.sys,'platform',platform)
    FakeClient.mode='full';FakeClient.stop_error=None
    output=tmp_path/'success.jsonl'
    asyncio.run(capture.run(SimpleNamespace(address='AA:BB:CC:DD:EE:FF',output=output,label='other',duration=.01,scan=False)))
    result=summary(output)
    assert result['recording_completed'] is True and result['error'] is None
    assert FakeClient.notify_options==options


def test_record_error_keeps_first_stage_when_cleanup_also_fails(monkeypatch, tmp_path):
    row = run_capture(monkeypatch, tmp_path, 'early_disconnect', EOFError('cleanup failed'))
    assert row['error'].startswith('Device disconnected')
    assert row['error_stage'] == 'record'
