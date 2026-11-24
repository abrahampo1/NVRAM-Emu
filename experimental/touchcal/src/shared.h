#ifndef SHARED_H
#define SHARED_H
typedef unsigned char u8; typedef unsigned short u16; typedef unsigned int u32; typedef int s32;
typedef volatile u8 vu8; typedef volatile u16 vu16; typedef volatile u32 vu32;
#define SHARED_ADDR 0x023F0000
typedef struct {
    u32 magic, beat;
    u32 down;          /* 1 = pen down (stable average valid) */
    u32 rx, ry;        /* averaged raw 12-bit ADC */
    u32 rx_min, rx_max;
} shared_t;
#define SH ((volatile shared_t *)SHARED_ADDR)
#endif
