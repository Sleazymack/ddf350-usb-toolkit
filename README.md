# DDF-350 USB Toolkit · 0.7.7
[Français](README.fr.md)

[Download Windows portable 0.7.7](https://github.com/Sleazymack/ddf350-usb-toolkit/releases/download/v0.7.7/DDF350-Portable-Public-v0.7.7.zip) · [Beta warning](BETA-WARNING.txt)

0.7.7 removes the GIF converter. Prepare the file externally; the app checks it, previews it and embeds its frames without resizing, palette reduction or timing changes. There is no imposed palette-color limit: colorful animations use the LCD's RGB565 format (up to 65,536 native shades). Files must be under 280 kB, 16–128 × 16–160 pixels with an even width, 2–20 frames, 200–1,000 ms per frame and no more than 4 seconds total. **GIFs can crash or freeze the transmitter even when they meet every requirement.** The warning remains visible before and after import. The new colorful player is tested in CPU emulation; hardware stability remains unverified.

A portable Windows x64 app for the DumboRC DDF-350. Read steering (CH1) and throttle/brake (CH2) over USB-C, choose one of nine dashboards, or build a layout with your own colors, gauges and photo. The optional PC reader can reconnect in the system tray.

0.7.6 adds an unchecked **Flash CH2 above +90** option to presets and the custom editor. The gauge and value flash at about 4 Hz while the displayed CH2 value is strictly above +90, and become steady at +90 or below. In the custom editor, choose a gauge and use **Solid background for this gauge…** to keep its card readable over a photo. Semicircles are now 8 pixels thick and bars 12 pixels tall, with opaque rounded backing cards. Previous compositions import into the new design format. The old firmware builders remain available for exact recognition of installations. New features are tested offline and in CPU emulation; hardware rendering remains unvalidated.

0.7.5 refines the three new dashboards with heavier, hinted Bahnschrift digits, aligned baselines, separately fitted percentage signs and a small binary LCD alphabet. Glyphs are drawn at their final native size, with no fractional scaling, dithering or partial alpha. The app still recognizes the exact 0.7.4 artwork when replacing an installed dashboard.

0.7.4 adds Equalizer Gold (red/green bars and gold half-dials), Classic Chrome (white dials and red needles), and Neon Hex (cyan/purple numeric panels). All three cover the 240 × 320 LCD, read CH1–CH4 from −100% to +100%, and use the live battery/USB indicator. They are adapted to native pixels from the supplied designs. New firmware generation and control updates are tested offline, including CPU emulation. Physical rendering and graphics heap headroom remain to be validated on a radio.

**Supported radio: DDF-350 hardware 1.0, application firmware 2.0.5.** Check both versions on the radio. Every GitHub release embeds the official DumboRC 2.0.5 application in the EXE. The wizard verifies its SHA-256 and uses it automatically as the base for your custom dashboard. The ZIP also contains the original file at `firmware/DDF-2.0.5.bin`. From official 1.2.0, use **3 · Update the radio · official firmware 2.0.5** on the home page. For other older versions, follow the [manufacturer’s update procedure](https://www.dumborc.com/?page_id=930).

1. Extract the public portable ZIP, then open **DDF350-USB-Toolkit.exe**. No Setup or Python required. The language selector is at the top right.
2. To install the exact manufacturer firmware, choose **3 · Update the radio · official firmware 2.0.5**. This four-step workflow supports official 1.2.0 and recognized 2.0.5-based installations. It restores the stock dashboard and startup and removes the PC USB workaround. It backs up the radio and verifies the transfer. The new update path has been tested offline, with hardware validation pending. To customize instead, choose a preset or **Custom**. In the editor’s **Style** tab, choose a photo and enable **Top: battery only** to show it across the upper area with a small live icon. Clear the option to bring back the stock upper display. The lower gauges and menu controls stay available.
3. In step 4, keep the stock startup, select a centered PNG/JPEG/BMP photo at 80%, or import a prepared GIF meeting the displayed requirements. Check the preview and select **Use this photo** or **Embed this GIF**. Unsupported files are refused; no converter is included.
4. Follow the connection and transfer steps in the wizard with the vehicle switched off. A recognized installation can be replaced. The Original dashboard preset retains the USB workaround; reinstall the official firmware to return the radio to stock. An unknown installed image stops the transfer. Do not unplug during writing or verification.
5. For PC inputs, boot normally and open **PC** in the app. Use the tray option if you want automatic reconnection.

Version 0.7.2 fixes a transfer interruption when Windows blocked replacement of status.json. If a previous attempt stopped, choose the same dashboard and options. The wizard reads and backs up the current radio again before transferring differing blocks. If it cannot recognize the radio, stop and retain the backup.

Photos use a native static image. GIF playback remains experimental: a freeze has been reported. The limits do not guarantee stability on the transmitter.

[Build and tests](CONTRIBUTING.md) · [Startup media](docs/startup-media.md) · [License](LICENSE) · [Credits](CREDITS.md)
