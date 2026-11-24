ENTRY(_start7)
SECTIONS {
  . = 0x037F8000;
  .text : { *(.crt0) *(.text*) *(.rodata*) }
  .data : { *(.data*) }
  .bss  : { *(.bss*) *(COMMON) }
  /DISCARD/ : { *(.ARM.exidx*) *(.comment) }
}
