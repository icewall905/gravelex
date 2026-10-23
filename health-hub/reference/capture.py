#!/usr/bin/env python3
"""Local BLE reference capture. Never uploads data or changes dashboard baselines."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time
import sys
from bluez_device import resolve_existing_device
from ble_rr import HEART_RATE_SERVICE,HEART_RATE_MEASUREMENT,decode_measurement,segmented_diagnostics


async def run(args):
    try:
        from bleak import BleakClient,BleakScanner
    except ImportError as error:
        raise SystemExit('Install reference/requirements.txt in a private virtual environment first.') from error
    if args.scan:
        found=await BleakScanner.discover(timeout=10,return_adv=True)
        for device,advertisement in found.values():
            if HEART_RATE_SERVICE in [v.lower() for v in advertisement.service_uuids] or 'hrm' in (device.name or '').lower():
                print(json.dumps({'address':device.address,'name':device.name,'services':advertisement.service_uuids}))
        return
    if not args.address or not args.output or not args.label:
        raise SystemExit('Capture requires --address, --output and an explicit --label.')
    output=Path(args.output)
    # Exclusive creation prevents erasing an earlier reference recording.
    descriptor=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    started=time.monotonic();sequence=0;rr=[];segments=[[]];packets=0;parse_errors=0;last_packet_at=None
    stages=[];current_stage=None;recording_started=None;notification_window_seconds=None
    recording_completed=False;error_stage=None
    disconnected=asyncio.Event()
    with os.fdopen(descriptor,'w',buffering=1) as stream:
        def record(value):
            stream.write(json.dumps(value,allow_nan=False)+'\n')
        def stage(name):
            nonlocal current_stage
            current_stage=name;stages.append(name);record({'type':'stage','stage':name,'at':time.time()})
        def disconnected_callback(_):
            disconnected.set()
        record({'type':'session','format_version':1,'label':args.label,
                'started_at':time.time(),'requested_seconds':args.duration,
                'source':'ble_heart_rate_rr','clock':'host_receive_unix_and_monotonic',
                'note':'Arrival times are not exact beat timestamps. Private local reference capture.'})
        def on_measurement(_,data):
            nonlocal sequence,packets,parse_errors,last_packet_at
            current=time.monotonic()
            if last_packet_at is not None and current-last_packet_at>5:
                segments.append([])
            last_packet_at=current
            sequence+=1;packets+=1
            base={'type':'measurement','sequence':sequence,'received_at':time.time(),
                  'elapsed_seconds':time.monotonic()-started,'packet_hex':bytes(data).hex()}
            try:
                decoded=decode_measurement(data)
                base.update(decoded)
                # Contact-off packets remain raw evidence but do not qualify.
                if not decoded['rr_ms']:
                    segments.append([])
                if decoded['contact_detected'] is not False:
                    for value in decoded['rr_ms']:
                        if value<=0:
                            segments.append([])
                        else:
                            rr.append(value);segments[-1].append(value)
                else:
                    segments.append([])
            except ValueError as error:
                base.update(type='parse_error',error=str(error));parse_errors+=1;segments.append([])
            record(base)
        error=None
        try:
            stage('connect')
            try:
                known=await asyncio.wait_for(resolve_existing_device(args.address),timeout=5)
            except asyncio.TimeoutError:
                known=None
            async with BleakClient(known or args.address,disconnected_callback=disconnected_callback,timeout=30) as client:
                record({'type':'connected','at':time.time(),'device_address':args.address})
                stage('subscribe')
                await client.start_notify(HEART_RATE_MEASUREMENT,on_measurement,**({'bluez':{'use_start_notify':True}} if sys.platform=='linux' else {}))
                stage('record')
                recording_started=time.monotonic()
                try:
                    await asyncio.wait_for(disconnected.wait(),timeout=args.duration)
                    error='Device disconnected; continuity is unknown. Capture stopped without reconnecting.'
                    error_stage='record'
                except asyncio.TimeoutError:
                    recording_completed=True
                    notification_window_seconds=time.monotonic()-recording_started
                    stage('completed')
                if client.is_connected:
                    stage('stop_notify')
                    try:
                        await client.stop_notify(HEART_RATE_MEASUREMENT)
                    except Exception as failure:
                        if error is None:
                            error=type(failure).__name__+': '+str(failure)
                            error_stage='stop_notify'
                stage('disconnect')
        except Exception as failure:
            if error is None:error=type(failure).__name__+': '+str(failure)
            if error_stage is None:error_stage=current_stage
        if recording_started is not None and notification_window_seconds is None:
            notification_window_seconds=time.monotonic()-recording_started
        if recording_completed and 'completed' not in stages:
            stage('completed')
        record({'type':'summary','ended_at':time.time(),'packets':packets,'parse_errors':parse_errors,
                'error':error,'error_stage':error_stage,'stages':stages,
                'recording_completed':recording_completed,
                'notification_window_seconds':notification_window_seconds,
                'diagnostic':segmented_diagnostics(segments),
                'qualified_reference':False,
                'note':'Reference eligibility requires review of gaps, contact and artifacts; no automatic watch calibration.'})
    print(json.dumps({'output':str(output),'packets':packets,'rr_intervals':len(rr),'parse_errors':parse_errors,
                      'error':error,'error_stage':error_stage,'recording_completed':recording_completed,
                      'notification_window_seconds':notification_window_seconds}))
    if error or not rr:
        raise SystemExit(1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan',action='store_true')
    parser.add_argument('--address')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--label',choices=['connection-check','quiet-seated','natural-movement','overnight','other'])
    parser.add_argument('--duration',type=int,default=210)
    args=parser.parse_args()
    if not 15<=args.duration<=3600:
        parser.error('Duration must be 15 to 3600 seconds')
    asyncio.run(run(args))


if __name__=='__main__':
    main()
