ENTRY(_start9)
SECTIONS {
  . = 0x02000000;
  .text : { *(.crt0) *(.text*) *(.rodata*) }
  .data : { *(.data*) }
  .bss  : { *(.bss*) *(COMMON) }
  /DISCARD/ : { *(.ARM.exidx*) *(.comment) }
}
