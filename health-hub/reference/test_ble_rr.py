import pytest
from ble_rr import decode_measurement,rr_diagnostics


def test_multiple_rr_values_keep_native_precision_order():
    value=decode_measurement(bytes([16,60,0,4,0,3,1,4]))
    assert value['rr_ticks']==[1024,768,1025]
    assert value['rr_ms']==[1000,750,1000.9765625]
    assert value['contact_detected'] is None


def test_uint16_hr_energy_and_contact():
    value=decode_measurement(bytes([31,44,1,7,0,0,4]))
    assert value['heart_rate_bpm']==300
    assert value['energy_kj']==7
    assert value['contact_detected'] is True
    assert value['rr_ms']==[1000]
    assert decode_measurement(bytes([4,60]))['contact_detected'] is False


@pytest.mark.parametrize('packet',[b'',bytes([1,60]),bytes([8,60,1]),bytes([16,60]),bytes([16,60,1]),bytes([0,60,1]),bytes([32,60])])
def test_malformed_packet_rejected(packet):
    with pytest.raises(ValueError):decode_measurement(packet)


def test_no_rr_flag_is_not_fabricated_hrv():
    assert decode_measurement(bytes([0,60]))['rr_ms']==[]
    assert rr_diagnostics([])['raw_rmssd_ms'] is None
    assert rr_diagnostics([1000,900,1000])['raw_rmssd_ms']==100


def test_segments_never_bridge_contact_or_packet_gap():
    from ble_rr import segmented_diagnostics
    result=segmented_diagnostics([[1000,1000],[],[500,500]])
    assert result['adjacent_pairs']==2
    assert result['raw_rmssd_ms']==0
