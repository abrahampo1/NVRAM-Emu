/* NVRAM-Emu diagnostics - ARM7 side: hardware probes, all with timeouts. */
#include "shared.h"

#define REG_SPICNT   (*(vu16*)0x040001C0)
#define REG_SPIDATA  (*(vu16*)0x040001C2)
#define REG_POWCNT2  (*(vu16*)0x04000304)
#define REG_WIFIWAIT (*(vu16*)0x04000206)
#define RTC_CR8      (*(vu8*)0x04000138)
#define W(off)       (*(vu16*)(0x04808000 + (off)))

static void delay(u32 n) { while (n--) __asm__ volatile("nop"); }

static int spi_wait(void) {
    for (u32 t = 0; t < 100000; t++) if (!(REG_SPICNT & 0x80)) return 0;
    SH->nv_spi_timeouts++; return -1;
}
static u8 spi_xfer(u8 v) { REG_SPIDATA = v; spi_wait(); return (u8)REG_SPIDATA; }

static void nvram_cmd(u8 cmd, u32 addr, int with_addr, volatile u8 *out, u32 n) {
    spi_wait();
    REG_SPICNT = 0x8900;               /* enable, NVRAM, hold CS, 4MHz */
    spi_xfer(cmd);
    if (with_addr) { spi_xfer(addr >> 16); spi_xfer(addr >> 8); spi_xfer(addr); }
    for (u32 i = 0; i < n; i++) {
        if (i == n - 1) { spi_wait(); REG_SPICNT = 0x8100; } /* release CS on last byte */
        out[i] = spi_xfer(0);
    }
    if (n == 0) { spi_wait(); REG_SPICNT = 0x8100; spi_xfer(0); }
    spi_wait(); REG_SPICNT = 0;
}

/* RTC (bit-banged, same protocol as libnds) */
#define CS_0 (1<<6)
#define CS_1 ((1<<6)|(1<<2))
#define SCK_0 (1<<5)
#define SCK_1 ((1<<5)|(1<<1))
#define SIO_1 ((1<<4)|(1<<0))
#define SIO_out (1<<4)
#define RD 48
static void rtc_xfer(u8 cmd, volatile u8 *res, u32 n) {
    RTC_CR8 = CS_0 | SCK_1 | SIO_1; delay(RD);
    RTC_CR8 = CS_1 | SCK_1 | SIO_1; delay(RD);
    u8 d = cmd;
    for (int b = 0; b < 8; b++) {
        RTC_CR8 = CS_1 | SCK_0 | SIO_out | (d >> 7); delay(RD);
        RTC_CR8 = CS_1 | SCK_1 | SIO_out | (d >> 7); delay(RD);
        d <<= 1;
    }
    for (u32 i = 0; i < n; i++) {
        u8 v = 0;
        for (int b = 0; b < 8; b++) {
            RTC_CR8 = CS_1 | SCK_0; delay(RD);
            RTC_CR8 = CS_1 | SCK_1; delay(RD);
            if (RTC_CR8 & 1) v |= (1 << b);
        }
        res[i] = v;
    }
    RTC_CR8 = CS_0 | SCK_1; delay(RD);
}

static void probe(void) {
    volatile shared_t *s = SH;
    s->powcnt2 = REG_POWCNT2;
    s->wifiwaitcnt = REG_WIFIWAIT;
    s->scfg_rom  = *(vu32*)0x04004000;
    s->scfg_ext7 = *(vu32*)0x04004008;
    s->scfg_wl   = *(vu32*)0x04004020;

    /* NVRAM */
    nvram_cmd(0x9F, 0, 0, s->nv_id, 3);
    nvram_cmd(0x05, 0, 0, &s->nv_sr, 1);
    nvram_cmd(0x03, 0x000000, 1, s->nv_hdr, 0x40);
    nvram_cmd(0x03, 0x01FE00, 1, s->nv_us, 0x20);

    /* DS-mode Wi-Fi: power on + wait states, then read ID / state registers */
    REG_POWCNT2 = REG_POWCNT2 | 2;
    REG_WIFIWAIT = 0x30;
    delay(20000);
    s->w_id = W(0x000);
    s->w_mode_rst = W(0x004);
    s->w_powerstate = W(0x03C);
    s->w_bb_busy = W(0x15E);
    s->w_rf_busy = W(0x180);
    /* Wi-Fi RAM read-back (0x04804000) */
    vu16 *ram = (vu16 *)0x04804000;
    u16 old = ram[0x100];
    ram[0x100] = 0xA55A;
    s->w_ram_read = ram[0x100];
    s->w_ram_ok = (s->w_ram_read == 0xA55A);
    ram[0x100] = old;
    /* baseband register 0 read with timeout */
    W(0x158) = 0x6000;
    u32 t;
    for (t = 0; t < 0x10000; t++) if (!(W(0x15E) & 1)) break;
    s->w_bb_timeout = (t == 0x10000);
    s->w_bb0 = W(0x15C);

    /* RTC: status register 1 (0x61) and date/time (0x65) */
    rtc_xfer(0x61, &s->rtc_stat, 1);
    rtc_xfer(0x65, s->rtc, 7);
}

void main7(void) {
    SH->magic = 0x4744564E;  /* 'NVDG' */
    for (;;) {
        probe();
        SH->round_done = 1;
        SH->heartbeat++;
        delay(2000000);
    }
}

__attribute__((naked, section(".crt0"))) void _start7(void) {
    __asm__ volatile(
        "mov r0, #0x04000000\n"
        "str r0, [r0, #0x208]\n"      /* IME = 0 */
        "ldr sp, =0x0380F000\n"
        "b main7\n");
}
