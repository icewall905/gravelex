#pragma once
#include <stdint.h>
#define MOTION_WINDOW_COUNT 36
#define MOTION_WINDOW_MS 5000
#define MOTION_WINDOW_VERSION 1
static inline uint8_t motion_window_bucket(uint32_t elapsed_ms) {
  uint32_t bucket=elapsed_ms/MOTION_WINDOW_MS;
  return bucket>=MOTION_WINDOW_COUNT?MOTION_WINDOW_COUNT-1:(uint8_t)bucket;
}
static inline uint32_t motion_axis_delta(int16_t x,int16_t y,int16_t z,int16_t px,int16_t py,int16_t pz) {
  int32_t dx=(int32_t)x-px,dy=(int32_t)y-py,dz=(int32_t)z-pz;
  if(dx<0) dx=-dx;
  if(dy<0) dy=-dy;
  if(dz<0) dz=-dz;
  return (uint32_t)(dx+dy+dz);
}
static inline void motion_window_add_sample(uint32_t elapsed_ms,uint16_t *samples,uint16_t *transitions,uint32_t *totals,uint32_t *peaks,uint32_t delta,uint8_t has_previous) {
  uint8_t bucket=motion_window_bucket(elapsed_ms); samples[bucket]++;
  if(!has_previous) return;
  transitions[bucket]++;
  totals[bucket]+=delta;
  if(delta>peaks[bucket]) peaks[bucket]=delta;
}
