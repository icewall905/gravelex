# PebbleOS PPI diagnostic instrumentation package

This is a source patch package for PebbleOS `v4.41.1` (`3e8d77c21d7188cfe873e8aa6312bf703f2566e3`) and the pinned Goodix integration (`d8ce9fc9bcc527094554bffc00822fb24d7907c1`). It is deliberately diagnostic-only: `CONFIG_HRM_PPI_DIAGNOSTICS` is off by default, depends on `CONFIG_HRM_HRV && LOG_HASHED`, changes no HRV decisions, and does not flash a watch or redistribute the vendor library.

## Applying the patch

Apply the source changes in the open PebbleOS checkout, then build the affected target with `CONFIG_HRM_HRV=y` and `CONFIG_HRM_PPI_DIAGNOSTICS=y` for a diagnostic image. Keep the normal build at its default (`n`). The patch changes these files:

* `drivers/hrm/Kconfig`: add `HRM_PPI_DIAGNOSTICS`, `bool`, `default n`, `depends on HRM_HRV && LOG_HASHED`.
* `drivers/hrm/gh3x2x.c`: add a guarded `uint32_t` result-id allocator and a diagnostic bridge accepting `(rri, confidence, valid_num, frame_id)`; its internal records carry the result ID, original count, index, PPI, confidence, wear, quality, forwarding decision and observed ticks. Allocate one ID per vendor result, before off-wrist/invalid handling. Preserve the existing `hrm_manager_new_data_cb()` calls and quality mapping. Clamp the original `valid_num` to four only for processing, and log the original count plus every skipped invalid value.
* `include/pbl/services/hrm/hrm_manager.h`: under the option only, add internal fields to `HRMData`: `uint32_t ppi_diag_result_id`, `uint32_t ppi_diag_frame_id`, `uint32_t ppi_diag_observed_ticks`, `uint16_t ppi_diag_result_index`, `int32_t ppi_diag_valid_num`, `int32_t ppi_diag_confidence`, `uint8_t ppi_diag_wear`, and `uint8_t ppi_diag_accepted`. Do not alter any public function signature or add an SDK symbol.
* `fw/services/hrm/hrm_manager.c`: copy those guarded fields into `HealthEventHRVUpdateData` and emit a `PPI_DIAG` manager line for each queued/delivered HRV event using the same ID and index. `ticks` is the monotonic `rtc_get_ticks()` value and must be documented as receipt time, never beat time.
* `fw/applib/health_service.h`: under the option only, add the same internal fields to `HealthEventHRVUpdateData`; existing public members (`ppi_ms`, `quality`) and callback signatures remain unchanged.
* `fw/applib/health_service.c`: immediately before the existing synchronous user callback, emit the app-stage line from the copied metadata. Do not expose metadata through a new SDK function.
* Pinned vendor hook source: transform only `GH3X2X_HrvAlgorithmResultReport()` so it passes `lubFrameId` to a newly named `gh3x2x_hrv_diag_bridge(...)`; leave the existing normal result bridge untouched. Use `vendor_hook_transform.py` here to verify the exact pinned source blob before producing the source patch.

The vendor hook must not call Pebble allocation, blocking APIs, or logging. The Pebble driver bridge logs with `PBL_LOG_DBG` only. No tokens, addresses, or identifiers that identify a person/device are logged.

## Line contract (schema 1)

Every line is one bounded record. Values are decimal integers except `stage` and the enumerated `skip` token. `rid` is a wrapping `uint32_t` result identity allocated once at the Goodix result boundary; `index` is the array ordinal. Neither is a beat identity. `ticks` is an observed monotonic receive tick (units are the platform RTC tick), not a beat timestamp.

```
PPI_DIAG v=1 stage=result rid=<u32> frame=<u32> count=<original-valid-num> confidence=<int> wear=<0|1> ticks=<u32>
PPI_DIAG v=1 stage=interval rid=<u32> index=<0..3> ppi=<int-ms> quality=<enum> ticks=<u32> accepted=<0|1> skip=<enum-int>
PPI_DIAG v=1 stage=manager rid=<u32> index=<0..3> ppi=<int-ms> quality=<enum> ticks=<u32> accepted=<0|1> skip=0
PPI_DIAG v=1 stage=app rid=<u32> index=<0..3> ppi=<int-ms> quality=<enum> ticks=<u32> accepted=<0|1> skip=0
```

`stage=result` is one summary per vendor result. `stage=interval` carries at most four array entries, including rejected entries; `manager` is the HRM/health queue boundary; `app` is immediately before the existing health callback. The result summary carries the vendor frame; interval frame is intentionally omitted to keep hashed log arguments bounded. `ticks` at each stage is sampled at that stage's boundary; the copied driver-origin tick remains internal metadata. `skip` is an integer enum, with `0=none`, `1=reserved`, `2=nonpositive_ppi`, `3=ppi_over_uint16`, and `4=clamped_count_tail`. `accepted` means forwarded through that boundary, while quality/wear retain physiological eligibility separately; no log claims consecutive beats.

## Verification requirements

Verify source identities before patching: Pebble source commit above, vendor commit above, and the hook blob SHA-256 recorded by the transformer. Apply `pebbleos-v4.41.1-ppi-diagnostics.patch` to a pristine checkout. A full firmware build is currently unverified: configuration stopped because `third_party/cmsis_core/CMSIS/CMSIS/Core/Include` is missing. For a future diagnostic build use `CONFIG_HRM_HRV=y`, `CONFIG_HRM_PPI_DIAGNOSTICS=y`, `DEFAULT_LOG_LEVEL_DEBUG=y`, and `FLASH_LOG_LEVEL_DEBUG=y`; `LOG_HASHED` must remain enabled. Decode the resulting hashed logs with the exact firmware build's `build/fw/loghash_dict.json` before parsing `PPI_DIAG` lines. Run the HRM manager/unit tests and a host accumulator test for result-id wrap, original-count >4, invalid-value skips, and stage key preservation. Inspect logs for equal `rid/index` keys across `result`, `interval`, `manager`, and `app`. Do not claim a full firmware build, device behavior, consecutive beats, or watch-app metadata availability until separately demonstrated.


## Checks completed and remaining

The six-file patch applies cleanly to the pinned pristine source. Fifteen parser/transformer tests pass. The isolated driver harness compiles the actual patched result function and HRMData with host platform stubs, diagnostics both on and off, with warnings treated as errors and undefined-behavior sanitizer. It checks forwarding counts, equal repeated intervals, invalid-value skips, count clamping, empty results, off-wrist handling and diagnostic metadata. Run it with:

```sh
python3 verify_driver.py /path/to/patched/PebbleOS
```

These checks do not establish full firmware compilation, queue correctness, result-ID wrap behavior on hardware, or sensor accuracy. Full firmware build, matching log dictionary generation, board-revision verification, official rollback image preservation and safe installation planning remain required before flashing. No watch firmware has been flashed by this package. Keep diagnostic logs private: interval values are health data even without direct identifiers. Debug logging may change timing and battery use; compare against the normal build.

Apply the open-source patch with `git apply --check` followed by `git apply` in the pinned PebbleOS checkout. Separately run `vendor_hook_transform.py SOURCE DESTINATION` against the pinned vendor hook (the transformer verifies its blob hash). No vendor library or complete vendor source is included here. Do not substitute another firmware/source version or flash an unverified image.
