#include "shared.h"
#include "font.h"
#define FB ((vu16*)0x06800000)
#define RGB(r,g,b) ((r)|((g)<<5)|((b)<<10)|0x8000)
#define T1X 32
#define T1Y 32
#define T2X 224
#define T2Y 160
static u32 udiv(u32 n,u32 d){ u32 q=0,r=0; for(int i=31;i>=0;i--){ r=(r<<1)|((n>>i)&1); if(r>=d){r-=d;q|=1u<<i;} } return q; }
static int sdiv(int n,int d){ int neg=(n<0)^(d<0); u32 q=udiv(n<0?-n:n,d<0?-d:d); return neg?-(int)q:(int)q; }
static u16 fg = RGB(31,31,31);
static int cx, cy;
static void px(int x,int y,u16 c){ if(x>=0&&x<256&&y>=0&&y<192) FB[y*256+x]=c; }
static void putc_(char c){
    if(c=='\n'){cx=0;cy+=FONT_H;return;}
    if(c<32||c>127)c='?';
    const u8*g=font[c-32];
    for(int y=0;y<FONT_H;y++)for(int x=0;x<FONT_W;x++) px(cx+x,cy+y,(g[y]>>(7-x))&1?fg:RGB(0,0,0));
    cx+=FONT_W;
}
static void puts_(const char*s){while(*s)putc_(*s++);}
static void num(u32 v,int d){ char b[8]; for(int i=d-1;i>=0;i--){u32 q=udiv(v,10); b[i]='0'+(v-q*10); v=q;} for(int i=0;i<d;i++)putc_(b[i]); }
static void at(int x,int y){cx=x;cy=y;}
static void cross(int x,int y,u16 c){ for(int i=-8;i<=8;i++){px(x+i,y,c);px(x,y+i,c);} }
static void clear(void){ for(int i=0;i<256*192;i++) FB[i]=RGB(0,0,0); }
static int lastx=-1,lasty=-1;
void main9(void){
    u32 c; __asm__ volatile("mrc p15,0,%0,c1,c0,0":"=r"(c)); c&=~((1<<0)|(1<<2)|(1<<12)); __asm__ volatile("mcr p15,0,%0,c1,c0,0"::"r"(c));
    *(vu16*)0x0400006C=0; *(vu16*)0x0400106C=0; *(vu16*)0x04000050=0; *(vu16*)0x04001050=0;
    *(vu32*)0x04001000=0x00010000; *(vu16*)0x05000400=0;
    *(vu16*)0x04000304 = 0x0203;      /* engine A on the BOTTOM screen */
    *(vu8*)0x04000240 = 0x80; *(vu32*)0x04000000 = 0x00020000;
    clear();
    volatile u8 *us = (volatile u8*)0x027FFC80;
    u32 ax1=us[0x58]|(us[0x59]<<8), ay1=us[0x5A]|(us[0x5B]<<8), sx1=us[0x5C], sy1=us[0x5D];
    u32 ax2=us[0x5E]|(us[0x5F]<<8), ay2=us[0x60]|(us[0x61]<<8), sx2=us[0x62], sy2=us[0x63];
    u32 cap[2][2]; int st=0, held=0;
    for(;;){
        cross(T1X,T1Y, st==0?RGB(31,31,0):RGB(8,31,8));
        cross(T2X,T2Y, st==1?RGB(31,31,0):(st>1?RGB(8,31,8):RGB(12,12,12)));
        at(48,56); fg=RGB(31,31,31);
        if(st<2){ puts_("Toca el centro de la cruz amarilla"); }
        else    { puts_("Listo. Haz una foto de la pantalla "); }
        at(48,70); puts_("CAL actual: "); num(ax1,4);putc_(' ');num(ay1,4);putc_(' ');num(sx1,3);putc_(' ');num(sy1,3);
        at(48,80); puts_("            "); num(ax2,4);putc_(' ');num(ay2,4);putc_(' ');num(sx2,3);putc_(' ');num(sy2,3);
        u32 down=SH->down, rx=SH->rx, ry=SH->ry;
        at(48,94); puts_("RAW "); if(down){num(rx,4);putc_(' ');num(ry,4);} else puts_("---- ----");
        puts_(SH->magic==0x4C434354?"  ARM7 ok":"  ARM7 ?");
        if(st>=1){ at(48,108); puts_("T1 "); num(cap[0][0],4);putc_(' ');num(cap[0][1],4); puts_(" -> 32,32"); }
        if(st>=2){ at(48,118); puts_("T2 "); num(cap[1][0],4);putc_(' ');num(cap[1][1],4); puts_(" -> 224,160"); }
        /* dot where the current calibration places the pen */
        if(lastx>=0){ for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++)px(lastx+dx,lasty+dy,RGB(0,0,0)); lastx=-1; }
        if(down && ax2!=ax1 && ay2!=ay1){
            int X=(int)sx1+sdiv(((int)rx-(int)ax1)*((int)sx2-(int)sx1),(int)ax2-(int)ax1);
            int Y=(int)sy1+sdiv(((int)ry-(int)ay1)*((int)sy2-(int)sy1),(int)ay2-(int)ay1);
            for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++)px(X+dx,Y+dy,RGB(31,0,31));
            lastx=X; lasty=Y;
        }
        if(st<2){
            if(down){ if(++held==30){ cap[st][0]=rx; cap[st][1]=ry; } }
            else { if(held>=30) st++; held=0; }
        }
        for(volatile int d=0; d<100000; d++);
    }
}
__attribute__((naked, section(".crt0"))) void _start9(void){
    __asm__ volatile("mov r0,#0x04000000\nstr r0,[r0,#0x208]\nldr sp,=0x023EF000\nb main9\n");
}
