# Rebuild the startup players

From the project root, create a temporary output directory and use Zig 0.13.0:

```powershell
$outDir = New-Item -ItemType Directory -Path (Join-Path $env:TEMP ('ddf-player-' + [guid]::NewGuid()))
$flags = @('-target','thumb-freestanding-eabi','-mcpu=cortex_m3','-Oz','-g','-ffreestanding','-fno-builtin','-fno-stack-protector','-ffunction-sections','-fdata-sections','-nostdlib','-Wl,--build-id=none','-Wl,-e,boot_start','-Wl,-T,startup/player.ld')
zig cc @flags -o "$outDir/v2.elf" startup/player.c
zig objcopy -O binary "$outDir/v2.elf" "$outDir/v2.bin"
python startup/export_player.py "$outDir/v2.elf" "$outDir/v2.bin" startup_player_blob.py
zig cc @flags -DDDF_SIMPLE_LOOP -o "$outDir/v3.elf" startup/player.c
zig objcopy -O binary "$outDir/v3.elf" "$outDir/v3.bin"
python startup/export_player.py "$outDir/v3.elf" "$outDir/v3.bin" startup_player_loop.py simple-loop
```

Version 1 remains available for exact recognition of older installations. The loop player stores ten deltas, displays each pose for 50 ms, resets the frame buffer at the cycle boundary and releases it after eight cycles. Timing in milliseconds refers to the native timer, not a physical display measurement.
