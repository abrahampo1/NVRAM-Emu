/* Shared result block between ARM7 (probes) and ARM9 (display). */
#ifndef SHARED_H
#define SHARED_H
typedef unsigned char u8; typedef unsigned short u16; typedef unsigned int u32;
typedef volatile u8 vu8; typedef volatile u16 vu16; typedef volatile u32 vu32;

#define SHARED_ADDR 0x023F0000
typedef struct {
    u32 magic;            /* 'NVDG' when ARM7 is alive */
    u32 heartbeat;        /* incremented every probe round */
    u32 round_done;
    /* power / config */
    u16 powcnt2, wifiwaitcnt;
    u32 scfg_rom, scfg_ext7, scfg_wl;
    /* NVRAM (SPI device 1) */
    u8  nv_id[3], nv_sr;
    u8  nv_hdr[0x40];
    u8  nv_us[0x20];
    u32 nv_spi_timeouts;
    /* DS-mode Wi-Fi */
    u16 w_id, w_mode_rst, w_powerstate, w_bb_busy, w_rf_busy, w_bb0;
    u32 w_bb_timeout;
    u32 w_ram_ok;         /* 1 = Wi-Fi RAM read-back OK */
    u16 w_ram_read;
    /* RTC */
    u8  rtc[7];
    u8  rtc_stat;
} shared_t;
#define SH ((volatile shared_t *)SHARED_ADDR)
#endif
