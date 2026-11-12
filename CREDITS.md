# Credits and scope

The firmware patcher, HID reader, capture tool and tests in this repository were developed for this independent USB investigation. They do not require or import another DDF-350 modding project.

[ELynx/ddf-350-modding](https://github.com/ELynx/ddf-350-modding) is a useful earlier source of community research and modding context. It is an independent GPL-3.0 project targeting different firmware, and was archived on 2025-10-04. No source file, binary release or Ghidra database from that repository is bundled here. A reference is not an endorsement or a compatibility claim.

Clock/peripheral analysis also consulted the primary [OpenLuat AIR32F103 SDK](https://github.com/openLuat/luatos-soc-air32f103) and [AIR32 enhancements documentation](https://wiki.luatos.org/chips/air32f103/enhancement.html). SDK similarities do not establish the exact physical chip fitted to every transmitter. Those SDK files are not redistributed here.

The optional emulation tests use separately installed Capstone and Unicorn packages under their own licenses. The ordinary patcher and PC tools use only Python's standard library. Optional startup image/GIF import and its preview use Pillow 12.3.0 (HPND and bundled third-party notices), whose complete installed LICENSE is included in packaged executables under third_party/pillow.

The original startup player is compiled using Zig 0.13.0. Its sources and linker
script are included; the compiled blob contains our code, without vendor code
or Zig runtime library symbols. The native graphics ABI was checked against the
locally supplied firmware, with LVGL's official documentation as a structural
reference. No LVGL source is copied into the player. A user's chosen animation
is selected locally in the application; it is not included in source
archives or default builds, and is not covered by this project's MIT license.

DumboRC supplies the official DDF-350 application firmware version 2.0.5 included as the base for dashboard generation. The original file is preserved byte for byte in the source checkout, release EXE and portable ZIP. The project's MIT license applies to its own code and documentation. DumboRC retains its rights to the firmware. Third-party projects and the bundled Python, Tk and Tcl components retain their respective licenses.

No startup GIF is bundled. Import a local file you have the right to use.
