ENTRY(boot_start)
SECTIONS {
 . = 0x080A8000;
 .player : { KEEP(*(.config)) KEEP(*(.text.boot_start)) KEEP(*(.text.boot_cleanup_hook)) *(.text*) KEEP(*(.rodata.boot_context*)) *(.rodata*) . = ALIGN(4); }
 /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) }
 .forbidden : { *(.data*) *(.bss*) *(COMMON) }
 ASSERT(SIZEOF(.forbidden) == 0, "Player must not appropriate global RAM")
 ASSERT(SIZEOF(.player) < 8192, "Player code exceeds its budget")
}
