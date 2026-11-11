# DDF-350 USB Toolkit 0.5.9 Portable — Experimental Beta

> **USE AT YOUR OWN RISK. Flashing can make your transmitter unusable, including bricking it. This is an unofficial experimental beta, supplied AS IS without warranty. The authors and contributors do not provide repair, replacement, reimbursement, or guaranteed recovery, to the extent permitted by applicable law.**

This repository distributes **only the Windows x64 portable version 0.5.9**. No Windows setup installer, version 0.6.0, startup GIF, or upper A/B dashboard editor is included.

## Download

[Download the portable 0.5.9 beta ZIP](https://github.com/Sleazymack/ddf350-usb-toolkit/releases/download/v0.5.9-beta/DDF350-USB-Toolkit-Portable-v0.5.9-beta.zip)

[Release notes and download page](https://github.com/Sleazymack/ddf350-usb-toolkit/releases/tag/v0.5.9-beta)

Extract the entire ZIP before launching `DDF350-USB-Toolkit.exe`. The app supports English and French. Exit any older running toolkit from its notification-area icon before opening this version.

ZIP SHA-256:
`77729f2014e5f849efdbbec4a38cbe3061909bcb9bd1906366edd2b7169717cd`

## Included

- The unchanged 0.5.9 portable executable.
- A step-by-step dashboard preparation and installation wizard, with a local backup, transfer log, and readback checks.
- Original, CH1–CH4, CH1–CH6, and custom lower-panel dashboard options.
- Live USB CH1/CH2 reading while the app is running or minimized, when the radio provides compatible USB reports.
- The exact official 2.0.5 application image, embedded in the executable and separately provided as `official-firmware-2.0.5/DDF.bin`.
- English instructions, the beta warning, original-code license, credits, and SHA-256 checksums.

The official image is 626,956 bytes, SHA-256:
`06c47e22049f0ec91823156b3a1afb997dfe31309d06c493aab08426d2866bbc`

## Compatibility and installation

Dashboard customization targets **DumboRC DDF-350 HW 1.0 with compatible official software 2.0.5**. An exact file hash does not prove compatibility with every radio or hardware revision.

1. Read [BETA-WARNING.txt](BETA-WARNING.txt).
2. Keep the vehicle powered off during installation and initial checks.
3. Extract the ZIP, start the application, and choose your language.
4. Confirm the supported radio version and follow the wizard.
5. Keep USB connected until instructed to disconnect. Preserve every backup and installation log.
6. Verify all controls before using the transmitter with a vehicle.

The application does not install a hardware driver. Windows startup registration is optional.

## Updating and going back

**Including the factory file is not a recovery guarantee.**

- Upgrading from an earlier firmware or a different bootloader must follow the manufacturer's applicable procedure. This wizard does not automate every older-version migration.
- The **Original** preset restores the original dashboard appearance while retaining USB/clock changes. It is **not** an exact factory-firmware restore.
- Version 0.5.9 has **no separate factory-restore button**. The provided original `DDF.bin` requires a compatible update/recovery procedure and a working maintenance mode.
- Do not bypass the unknown-firmware guard or blindly write to an unrecognized radio. Preserve the backup instead.
- Recovery of a failed or bricked transmitter is not guaranteed. The bootloader and settings are not backed up or repaired merely by including an application image.

[Manufacturer download/procedure page](https://www.dumborc.com/?page_id=930). This community project is not the manufacturer's official software or support service.

## Beta status and warranty

This is test software. Bugs, freezes, USB interruptions, incorrect behavior, data/settings loss, and an unusable transmitter are possible. Local software checks are not a complete hardware, RF, or long-term reliability validation. The executable is unsigned.

The software is supplied **AS IS**, without warranties of functionality, compatibility, reliability, fitness for a particular purpose, or recoverability. The authors and contributors accept no liability for resulting loss or damage and do not provide repair, replacement, reimbursement, or guaranteed recovery, **to the extent permitted by applicable law**. Nothing here excludes rights or liabilities that cannot lawfully be excluded.

See [BETA-WARNING.txt](BETA-WARNING.txt) and the `LICENSE` included in the ZIP.

## Third-party firmware

This is an independent community project, not affiliated with or endorsed by DumboRC. Manufacturer firmware and branding remain their owners' property. The MIT license covering the project's original code does **not** license the manufacturer's firmware. The manufacturer's image is unmodified in the supplied official-file copy.

## Bug reports

When reporting a problem, include your hardware/software version, the selected dashboard, and the failure stage. Remove serial numbers, personal paths, and other private information from any logs before posting them. Never upload a raw memory backup publicly.
