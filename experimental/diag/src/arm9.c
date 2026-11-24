/* NVRAM-Emu diagnostics - ARM9 side: shows the ARM7 probe results. */
#include "shared.h"
#include "font.h"   /* FONT_W x FONT_H glyphs for ASCII 32..127, 1 byte per row */

#define REG_DISPCNT  (*(vu32*)0x04000000)
#define REG_POWCNT1  (*(vu16*)0x04000304)
#define REG_VRAMCNT_A (*(vu8*)0x04000240)
#define FB ((vu16*)0x06800000)
#define RGB(r,g,b) ((r) | ((g) << 5) | ((b) << 10) | 0x8000)

static u16 fg = RGB(31,31,31);
static int cx, cy;

static void putc_(char c) {
    if (c == '\n') { cx = 0; cy += FONT_H; return; }
    if (c < 32 || c > 127) c = '?';
    const u8 *g = font[c - 32];
    for (int y = 0; y < FONT_H; y++)
        for (int x = 0; x < FONT_W; x++)
            FB[(cy + y) * 256 + cx + x] = (g[y] >> (7 - x)) & 1 ? fg : RGB(0,0,0);
    cx += FONT_W;
    if (cx + FONT_W > 256) { cx = 0; cy += FONT_H; }
}
static void puts_(const char *s) { while (*s) putc_(*s++); }
static void hex(u32 v, int digits) {
    for (int i = digits - 1; i >= 0; i--) putc_("0123456789ABCDEF"[(v >> (i * 4)) & 0xF]);
}
static void dec2(u8 bcd) { hex(bcd, 2); }
static void col(int ok) { fg = ok ? RGB(8,31,8) : RGB(31,8,8); }
static void white(void) { fg = RGB(31,31,31); }
static void verdict(int ok, const char *good, const char *bad) {
    col(ok); puts_(ok ? good : bad); white(); putc_('\n');
}

static int all_same(volatile u8 *p, int n, u8 v) { for (int i = 0; i < n; i++) if (p[i] != v) return 0; return 1; }

static void draw(void) {
    volatile shared_t *s = SH;
    cx = cy = 0; white();
    puts_("NVRAM-Emu diag v2   ARM7 #"); hex(s->heartbeat, 4); putc_('\n');
    puts_("POWCNT2="); hex(s->powcnt2, 4); puts_(" WAITCNT="); hex(s->wifiwaitcnt, 4); putc_('\n');
    puts_("SCFG "); hex(s->scfg_rom, 4); putc_(' '); hex(s->scfg_ext7, 8); putc_(' '); hex(s->scfg_wl, 4); putc_('\n');

    puts_("-- NVRAM (SPI flash) --\n");
    puts_("RDID "); hex(s->nv_id[0],2); hex(s->nv_id[1],2); hex(s->nv_id[2],2);
    puts_("  SR "); hex(s->nv_sr,2); puts_("  TO "); hex(s->nv_spi_timeouts,2); putc_('\n');
    puts_("HDR20 "); for (int i = 0x20; i < 0x30; i++) hex(s->nv_hdr[i], 2); putc_('\n');
    puts_("MAC   "); for (int i = 0x36; i < 0x3C; i++) hex(s->nv_hdr[i], 2); putc_('\n');
    puts_("USER  "); for (int i = 0; i < 0x10; i++) hex(s->nv_us[i], 2); putc_('\n');
    int nv_dead = all_same(s->nv_hdr, 0x40, 0xFF) || all_same(s->nv_hdr, 0x40, 0x00);
    verdict(!nv_dead, "NVRAM: RESPONDE", "NVRAM: SIN RESPUESTA (FF/00)");

    puts_("-- WIFI modo DS --\n");
    puts_("W_ID "); hex(s->w_id,4); puts_(" RST "); hex(s->w_mode_rst,4); puts_(" PWR "); hex(s->w_powerstate,4); putc_('\n');
    puts_("BBBUSY "); hex(s->w_bb_busy,4); puts_(" RFBUSY "); hex(s->w_rf_busy,4); putc_('\n');
    puts_("BB0 "); hex(s->w_bb0,4); puts_(s->w_bb_timeout ? " (TIMEOUT)" : " (ok)");
    puts_(" RAM "); hex(s->w_ram_read,4); putc_('\n');
    int wifi_ok = s->w_ram_ok && s->w_id != 0xFFFF && s->w_id != 0x0000;
    verdict(wifi_ok, "WIFI DS: RESPONDE", "WIFI DS: SIN RESPUESTA");

    puts_("-- RELOJ (RTC) --\n");
    puts_("20"); dec2(s->rtc[0]); putc_('-'); dec2(s->rtc[1]); putc_('-'); dec2(s->rtc[2]);
    putc_(' '); dec2(s->rtc[4] & 0x3F); putc_(':'); dec2(s->rtc[5]); putc_(':'); dec2(s->rtc[6]);
    puts_("  ST "); hex(s->rtc_stat,2); putc_('\n');
    int rtc_ok = !all_same(s->rtc, 7, 0xFF) && !all_same(s->rtc, 7, 0x00);
    verdict(rtc_ok, "RTC: RESPONDE (mira si avanza)", "RTC: SIN RESPUESTA");
    puts_("\nHaz una foto de esta pantalla.\n");
}

void main9(void) {
    /* caches/MPU off so ARM7 results are always visible */
    u32 c;
    __asm__ volatile("mrc p15, 0, %0, c1, c0, 0" : "=r"(c));
    c &= ~((1 << 0) | (1 << 2) | (1 << 12));
    __asm__ volatile("mcr p15, 0, %0, c1, c0, 0" :: "r"(c));
    *(vu16*)0x0400006C = 0;        /* MASTER_BRIGHT engine A: cancel loader fade */
    *(vu16*)0x0400106C = 0;        /* MASTER_BRIGHT engine B */
    *(vu16*)0x04000050 = 0;        /* BLDCNT A */
    *(vu16*)0x04001050 = 0;        /* BLDCNT B */
    *(vu32*)0x04001000 = 0x00010000; /* engine B: normal mode, no layers */
    *(vu16*)0x05000400 = 0;        /* engine B backdrop colour = black */
    REG_POWCNT1 = 0x8203;          /* LCDs on, 2D A + 2D B, A on top screen */
    REG_VRAMCNT_A = 0x80;          /* VRAM A in LCDC mode */
    REG_DISPCNT = 0x00020000;      /* display mode 2: framebuffer from VRAM A */
    for (int i = 0; i < 256 * 192; i++) FB[i] = RGB(0,0,0);
    cx = cy = 0;
    puts_("Esperando al ARM7...\n");
    for (;;) {
        if (SH->magic == 0x4744564E && SH->round_done) draw();
        for (volatile int d = 0; d < 400000; d++);
    }
}

__attribute__((naked, section(".crt0"))) void _start9(void) {
    __asm__ volatile(
        "mov r0, #0x04000000\n"
        "str r0, [r0, #0x208]\n"
        "ldr sp, =0x023EF000\n"
        "b main9\n");
}
