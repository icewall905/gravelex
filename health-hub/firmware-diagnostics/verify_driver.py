#!/usr/bin/env python3
"""Compile the patched driver's actual result function against host platform stubs.

This isolates forwarding semantics; it does not validate firmware queues or hardware.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

PRELUDE = r'''
#include <stdint.h>
#include <stdbool.h>
#include <inttypes.h>
#include <stdio.h>
#include <assert.h>
#define UNUSED_VAR(x) (void)(x)
#define PBL_LOG_DBG(...) do { if (0) printf(__VA_ARGS__); } while (0)
#define GH3X2X_HRV_MAX_RRI_PER_RESULT 4
typedef int HRMFeature;
typedef int HRMQuality;
enum { HRMFeature_HRV=1, HRMQuality_OffWrist, HRMQuality_Excellent,
 HRMQuality_Good, HRMQuality_Acceptable, HRMQuality_Poor, HRMQuality_Worst };
struct State { unsigned is_wear; } state;
struct Device { struct State *state; } device = { &state };
#define HRM (&device)
#ifdef CONFIG_HRM_PPI_DIAGNOSTICS
static uint32_t rtc_get_ticks(void) { return 123; }
#endif
'''
TEST = r'''
static void run(const int32_t *values, int count, unsigned wear, int expected) {
 n=0; state.is_wear=wear;
#ifdef CONFIG_HRM_PPI_DIAGNOSTICS
 gh3x2x_hrv_diag_bridge(values, 99, count, 42);
#else
 gh3x2x_hrv_result_report(values, 99, count);
#endif
 assert(n==expected);
 for(int i=0;i<n;i++) {
   assert(out[i].hrv_quality==(wear ? HRMQuality_Excellent : HRMQuality_OffWrist));
#ifdef CONFIG_HRM_PPI_DIAGNOSTICS
   assert(out[i].ppi_diag_present==1);
   assert(out[i].ppi_diag_frame_id==42);
   assert(out[i].ppi_diag_valid_num==count);
   assert(out[i].ppi_diag_observed_ticks==123);
   assert(out[i].ppi_diag_accepted==1);
   assert(out[i].ppi_diag_wear==wear);
   if(i) assert(out[i].ppi_diag_result_id==out[0].ppi_diag_result_id);
#endif
 }
}
int main(void) {
 int32_t good[4]={800,900,1000,1100}, bad[4]={-1,70000,1000,1000};
 run(good,2,1,2); assert(out[0].hrv_ppi_ms==800 && out[1].hrv_ppi_ms==900);
 run(bad,4,1,2); assert(out[0].hrv_ppi_ms==1000 && out[1].hrv_ppi_ms==1000);
#ifdef CONFIG_HRM_PPI_DIAGNOSTICS
 assert(out[0].ppi_diag_result_index==2 && out[1].ppi_diag_result_index==3);
#endif
 run(good,8,1,4); run(good,0,1,0); run(good,-1,1,0);
 run(good,4,0,1); assert(out[0].hrv_ppi_ms==0);
 puts("forwarding cases passed");
}
'''

def main():
 p=argparse.ArgumentParser(); p.add_argument('source',type=Path); args=p.parse_args()
 driver=(args.source/'drivers/hrm/gh3x2x.c').read_text()
 start=driver.index('static void prv_hrv_result_report(')
 end=driver.index('\n#endif\n#endif',start)
 body=driver[start:end]+'\n#endif\n'
 header=(args.source/'include/pbl/services/hrm/hrm_manager.h').read_text()
 end=header.index('} HRMData;')+len('} HRMData;')
 start=header.rfind('typedef struct {',0,end)
 struct=header[start:end]
 capture='\nstatic HRMData out[8]; static int n;\nstatic void hrm_manager_new_data_cb(HRMData *d) { assert(n<8); out[n++]=*d; }\n'
 with tempfile.TemporaryDirectory(prefix='ppi-driver-') as tmp:
  source=Path(tmp)/'test.c'; source.write_text(PRELUDE+struct+capture+body+TEST)
  for enabled in (False,True):
   binary=Path(tmp)/('on' if enabled else 'off')
   cmd=['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined','-o',str(binary),str(source)]
   if enabled: cmd.append('-DCONFIG_HRM_PPI_DIAGNOSTICS=1')
   subprocess.run(cmd,check=True); subprocess.run([str(binary)],check=True)
 print('Both option states passed (isolated driver only).')
if __name__=='__main__': main()
