#include "shared.h"
#define SPICNT  (*(vu16*)0x040001C0)
#define SPIDATA (*(vu16*)0x040001C2)
#define KEYXY   (*(vu16*)0x04000136)
static void w(void){ for (u32 t=0;t<100000;t++) if(!(SPICNT&0x80)) return; }
static u16 tsc(u8 cmd){
    w(); SPICNT = 0x8A01; SPIDATA = cmd; w();
    SPIDATA = 0; w(); u16 a = SPIDATA & 0xFF;
    SPICNT = 0x8201; SPIDATA = 0; w(); u16 b = SPIDATA & 0xFF;
    SPICNT = 0;
    return ((a & 0x7F) << 5) | (b >> 3);
}
static u32 udiv(u32 n,u32 d){ u32 q=0,r=0; for(int i=31;i>=0;i--){ r=(r<<1)|((n>>i)&1); if(r>=d){r-=d;q|=1u<<i;} } return q; }
void main7(void){
    SH->magic = 0x4C434354;
    for(;;){
        SH->beat++;
        if (KEYXY & 0x40) { SH->down = 0; continue; }
        u32 sx=0, sy=0, n=0, mn=0xFFFF, mx=0;
        for (int i=0;i<32;i++){
            u16 x=tsc(0xD1), y=tsc(0x91);
            if (x==0||y==0||x>=4095||y>=4095) continue;
            sx+=x; sy+=y; n++; if(x<mn)mn=x; if(x>mx)mx=x;
        }
        if (KEYXY & 0x40 || n<16) { SH->down=0; continue; }
        SH->rx=udiv(sx,n); SH->ry=udiv(sy,n); SH->rx_min=mn; SH->rx_max=mx; SH->down=1;
    }
}
__attribute__((naked, section(".crt0"))) void _start7(void){
    __asm__ volatile("mov r0,#0x04000000\nstr r0,[r0,#0x208]\nldr sp,=0x0380F000\nb main7\n");
}
