#include <assert.h>
#include "../src/c/motion_windows.h"
int main(void){uint16_t s[36]={0},t[36]={0};uint32_t d[36]={0},p[36]={0};assert(MOTION_WINDOW_VERSION==1);motion_window_add_sample(4999,s,t,d,p,0,0);motion_window_add_sample(5000,s,t,d,p,7,1);motion_window_add_sample(180000,s,t,d,p,11,1);assert(s[0]==1&&s[1]==1&&s[35]==1);assert(t[1]==1&&t[35]==1);assert(d[1]==7&&p[35]==11);return 0;}
