# Build and test 0.7.1

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

The checked-in Python player modules contain compiled original code and can be used without an ARM compiler. To reproduce player versions 2 and 3 from `startup/player.c` with Zig 0.13.0, see [the build commands](docs/startup-animation.md). See [CREDITS.md](CREDITS.md) for dependencies and licenses.
