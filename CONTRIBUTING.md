# Build and test 0.7.7

Use Windows x64, 64-bit Python with Tk (3.10 or later) and PowerShell. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe app.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

To build the public one-file executable:

```powershell
.\build_windows.ps1 -Python .\.venv\Scripts\python.exe
```

Every release build reads `firmware/DDF-2.0.5.bin` from the checkout. It checks the official size and SHA-256 before compiling, then extracts and verifies that resource inside the finished EXE. The build writes the portable ZIP, its SHA-256 checksum and a build report outside the source tree. Upload the generated public ZIP and checksum as release assets. Both the EXE and the ZIP contain the verified firmware; no startup media is bundled.

For firmware integration and CPU tests, install `tests/requirements-arm.txt`, set `DDF350_OFFICIAL_FIRMWARE` to the absolute path of the included `firmware/DDF-2.0.5.bin` and rerun the suite. Its size and SHA-256 are recorded in [compatibility.json](compatibility.json). Keep radio backups, logs and personal media local.

The checked-in Python player modules contain compiled original code and can be used without an ARM compiler. Reproduce versions 2 and 3 from `startup/player.c`, and RGB565 version 4 from `startup/player-rgb.c`, with Zig 0.13.0 using [the build commands](docs/startup-animation.md). See [CREDITS.md](CREDITS.md) for dependencies and licenses.

There is no GIF converter or conversion CLI. `startup/gif_import.py` validates prepared GIFs; `startup/gif_codec.py` packages unchanged frame pixels into bounded native deltas. No resizing, palette quantization, frame dropping or timing adjustment runs for GIFs. The LCD's native RGB565 representation is still necessary. Up to 16 colors use the exact older compact player; other GIFs use v4 with a maximum 40,960-byte frame buffer. Tests verify source pixels, multiple local palettes, byte order, bounds, allocation failures, cleanup, legacy recognition and replacement. These are offline tests, not physical stability measurements.

Rebuild the additional native presets with `python artwork/compile_extra_faces.py` on Windows with the pinned Pillow version and system Bahnschrift font. This writes `dashboard_extra_assets.py`. Existing preset assets are preserved for exact recognition of earlier installations.

The frozen `dashboard_extra_assets_v074.py` retains the previous three artwork banks. Current gallery entries use new internal keys. `tests/legacy-074-extra-faces.json` pins the six earlier images for bit-exact recognition tests. Rebuilding current artwork also uses `artwork/pixel_font.py`.

Current custom cards use schema 13 with a per-widget `background`, a boolean `full_background` and an explicit `blink_ch2` boolean. Schema 14 enables the optional alarm on indexed graphic presets. Schema 15 adds it to native presets. Existing schemas continue to regenerate their historical bytes. The alarm reads the existing LVGL timer timestamp and changes only owned/validated visual flags, with no new timer, global RAM, RF setting or command-value write. Use `--blink-ch2` for the optional CLI equivalent.
