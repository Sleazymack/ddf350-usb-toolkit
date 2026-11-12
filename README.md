# DDF-350 USB Toolkit · 0.7.1
[Français](README.fr.md)

[Download the Windows portable ZIP for 0.7.1](https://github.com/Sleazymack/ddf350-usb-toolkit/releases/download/v0.7.1/DDF350-Portable-Public-v0.7.1.zip) · [Release notes](https://github.com/Sleazymack/ddf350-usb-toolkit/releases/tag/v0.7.1) · [Beta warning](BETA-WARNING.txt)

A portable Windows x64 app for the DumboRC DDF-350. Read steering (CH1) and throttle/brake (CH2) over USB-C, choose one of six dashboards, or build a layout with your own colors, gauges and photo. The optional PC reader can reconnect in the system tray.

**Supported radio: DDF-350 hardware 1.0, application firmware 2.0.5.** Check both versions on the radio. Every GitHub release embeds the official DumboRC 2.0.5 application in the EXE. The wizard verifies its SHA-256 and uses it automatically as the base for your custom dashboard. The ZIP also contains the original file at `firmware/DDF-2.0.5.bin`. For a radio running an older version, follow the [manufacturer’s update procedure](https://www.dumborc.com/?page_id=930) first.

1. Extract the public portable ZIP, then open **DDF350-USB-Toolkit.exe**. No Setup or Python required. The language selector is at the top right.
2. Choose a preset or **Custom**. In the editor’s **Style** tab, choose a photo and enable **Top: battery only** to show it across the upper area with a small live icon. Clear the option to bring back the stock upper display. The lower gauges and menu controls stay available.
3. In step 4, keep the stock startup, select a centered PNG/JPEG/BMP photo at 80%, or import your own GIF under 280 kB, up to 5 fps and 4 seconds. Check the preview and select **Use this preview**.
4. Follow the connection and transfer steps in the wizard with the vehicle switched off. A recognized installation can be replaced. The Original dashboard preset retains the USB workaround; reinstall the official firmware to return the radio to stock. An unknown installed image stops the transfer. Do not unplug during writing or verification.
5. For PC inputs, boot normally and open **PC** in the app. Use the tray option if you want automatic reconnection.

Photos use a native static image. GIF playback remains experimental: a freeze has been reported. The limits do not guarantee stability on the transmitter.

[Build and tests](CONTRIBUTING.md) · [Startup media](docs/startup-media.md) · [License](LICENSE) · [Credits](CREDITS.md)
