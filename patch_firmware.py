#!/usr/bin/env python3
"""Offline DDF-350 2.0.5 patcher with an exact pinned input (Python 3.10+).

This program creates a separate file. It does not install firmware, enumerate
USB devices, open a radio, or change a bootloader. No vendor firmware is bundled.
The portable stock-based outputs have NOT been tested on hardware. Measurements
published with this project concern a different, customized firmware build.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import struct
import sys

import dashboard_six
import dashboard_custom
import startup_animation as startup
import startup_photo as photo

VERSION = "0.7.1-experimental"
IS_WINDOWS = sys.platform == "win32"
FLASH_BASE = 0x08005000
ORIGINAL_SIZE = 626956
ORIGINAL_SHA256 = "06c47e22049f0ec91823156b3a1afb997dfe31309d06c493aab08426d2866bbc"
CLOCK_SHA256 = "b122be6391d42354bff9d4e146526dcca323d277abecc1a999f539276af6902c"
FAST_SIZE = 627232
FAST_SHA256 = "9afd478afc6085b48435816273f844ff277facbb48d7116f5bfe84daa0cbf250"
CLOCK_CH1234_SHA256 = "ab1e07209af3ded75a70f5567dc598ba33ec05de9cd771edee27448b9f8bf67e"
FAST_CH1234_SHA256 = "3f67d80255dca8fe7c3544ad7417bc88b4067f3bce01e4899913187e6f1095de"
CLOCK_CH123456_SIZE = 629292
FAST_CH123456_SIZE = 629568
CLOCK_CH123456_SHA256 = "f622f91d45b0bc1063cb3c11ff1a82806f2160a91213bfa65db27f34e237f365"
FAST_CH123456_SHA256 = "cb8b9e6f3c3685f874709f93efc7a4b605c4f2384b6f456efbcf7b11570ffdc4"
BODY_START, BODY_END = 0x2C8A2, 0x2C97C
BODY_SHA256 = "453aeb70877aeb7e9b706a98d9d9716da1206e9d248bf7f6f59da5cc22567d51"
SOURCE_POINTER_OFFSET = 0x2C9AC
SOURCE_POINTER = 0x200001A0
SOURCE_LOAD_OFFSETS = (0, 34, 114, 126, 140, 154, 166, 180, 194, 206)

# Small before/after signatures, not a copy of the firmware or its decoder.
ORIGINAL_SITES = {
    0x21B0E: bytes.fromhex("24"),
    BODY_START: bytes.fromhex("4248b0f81300"),
    0x2C986: bytes.fromhex("0120fcf700fc002005490870"),
    0x2C992: bytes.fromhex("1420"),
    0x96F23: bytes.fromhex("14"),
}
# Native home rows only: data pointers and their fixed labels. Colors, geometry,
# widgets, caches, menus, channel calculation and RF/USB data are not changed.
DASHBOARD_PATCHES = (
    (0x3BF4, bytes.fromhex("14020020"), bytes.fromhex("0c020020")),
    (0x3CCC, bytes.fromhex("18020020"), bytes.fromhex("10020020")),
    (0x57C58, b"CH5\0", b"CH3\0"),
    (0x57C60, b"CH6\0", b"CH4\0"),
)
VARIANTS = {
    ORIGINAL_SHA256: ("original-2.0.5", ORIGINAL_SIZE),
    CLOCK_SHA256: ("clock192", ORIGINAL_SIZE),
    FAST_SHA256: ("clock192-usb1ms", FAST_SIZE),
    CLOCK_CH1234_SHA256: ("clock192-ch1234", ORIGINAL_SIZE),
    FAST_CH1234_SHA256: ("clock192-usb1ms-ch1234", FAST_SIZE),
    CLOCK_CH123456_SHA256: ("clock192-ch123456", CLOCK_CH123456_SIZE),
    FAST_CH123456_SHA256: ("clock192-usb1ms-ch123456", FAST_CH123456_SIZE),
}
MAX_CUSTOM_IMAGE_SIZE = dashboard_custom.wallpaper.END + dashboard_custom.LAYOUT_MAX_BYTES + 24
MAX_IMAGE_SIZE = startup.MAX_IMAGE_SIZE
LIMITS = (
    "Exact firmware hash is not proof of hardware compatibility.",
    "These portable stock-based outputs are not hardware-tested.",
    "CPU clock changes also affect other peripherals; RF driving is not validated.",
    "USB reset/reconnection can leave the native ready flag cleared; a complete power restart may be needed.",
    "An intermittent menu freeze was reported on the customized build, not reproduced in a later test; its cause remains unknown.",
    "1 ms is a requested USB interval, not an end-to-end latency guarantee.",
    "Channel production remains nominally 20 ms (Normal) or 6 ms (Fast); this tool does not change model settings.",
    "The six-row dashboard is not visually or physically validated; CH3/CH4 use direct rounded values, while four existing bars retain native filtering.",
    "Custom layouts add up to 28 native widgets; graphics heap headroom and physical rendering are unmeasured. Their channel values are direct, rounded and unfiltered.",
    "The two-zone dashboard and optional startup player are offline-validated, not hardware-tested; actual boot timing and LCD rendering remain unmeasured.",
    "The three fixed drift themes add up to 49 owned objects and normalize display to +/-100%; actual graphics heap headroom and LCD rendering remain unmeasured.",
)


class PatchError(ValueError):
    """A firmware or local-file safety condition was not met."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require(condition: bool, message: str) -> None:
    # Explicit exceptions are required: guards must also work under python -O.
    if not condition:
        raise PatchError(message)


def _halfwords(*values: int) -> bytes:
    return struct.pack("<" + "H" * len(values), *values)


def _branch(address: int, target: int, *, link: bool = False) -> bytes:
    """Encode Thumb-2 B.W/BL; caller supplies even instruction addresses."""
    delta = target - (address + 4)
    _require(address % 2 == 0 and target % 2 == 0, "Unaligned Thumb branch.")
    _require(-(1 << 24) <= delta < (1 << 24), "Thumb branch is out of range.")
    sign = (delta >> 24) & 1
    j1 = 1 ^ ((delta >> 23) & 1) ^ sign
    j2 = 1 ^ ((delta >> 22) & 1) ^ sign
    return _halfwords(
        0xF000 | (sign << 10) | ((delta >> 12) & 0x3FF),
        (0xD000 if link else 0x9000) | (j1 << 13) | (j2 << 11) | ((delta >> 1) & 0x7FF),
    )


def inspect_image(image: bytes) -> dict:
    if len(image) == photo.END and image[photo.HOOK:photo.HOOK+4] == photo.BRANCH:
        try:
            base,pixels=photo.unpack(image)
            info=inspect_image(base)
            _require(info['recognized'] and info['variant']!='original-2.0.5' and
                     not info.get('startup_animation') and photo.attach(base,pixels)==image,
                     'Startup photo differs from complete regeneration.')
            return dict(info,bytes=len(image),sha256=sha256(image),base_variant=info['variant'],
                        variant=info['variant']+'-startup-photo',startup_photo=True)
        except (ValueError,TypeError,KeyError,struct.error):
            pass
    if image.endswith(startup.TRAILER_MAGIC):
        try:
            base,asset,player_version=startup.unpack(image,with_version=True)
            info=inspect_image(base)
            _require(info['recognized'] and not info.get('startup_animation'), 'Unknown startup base.')
            _require(startup.attach(base,asset,player_version=player_version)==image, 'Startup image differs from full regeneration.')
            return dict(info, bytes=len(image),sha256=sha256(image),base_variant=info['variant'],
                        variant=info['variant']+'-startup-animation'+(f'-v{player_version}' if player_version>=2 else ''),startup_animation=startup.description(asset),
                        startup_player_version=player_version,
                        startup_verified_by_complete_regeneration=True)
        except (ValueError,TypeError,KeyError,struct.error,RecursionError):
            pass
    digest = sha256(image)
    known = VARIANTS.get(digest)
    recognized = known is not None and len(image) == known[1]
    custom = _recognize_custom(image) if not recognized else None
    report = {
        "schema": 1,
        "tool_version": VERSION,
        "bytes": len(image),
        "sha256": digest,
        "recognized": recognized or custom is not None,
        "variant": known[0] if recognized else custom["variant"] if custom else "unsupported",
        "dashboard": ("ch123456" if known[0].endswith("-ch123456") else
                      "ch1234" if known[0].endswith("-ch1234") else "original") if recognized else "custom" if custom else None,
        "portable_output_hardware_tested": False,
        "hardware_compatibility_determined": False,
    }
    if custom:
        report["layout"] = custom["layout"]
        report["custom_verified_by_complete_regeneration"] = True
    return report


def _require_original(original: bytes) -> None:
    _require(len(original) == ORIGINAL_SIZE, "Expected the exact 626956-byte original 2.0.5 file.")
    _require(sha256(original) == ORIGINAL_SHA256, "Original firmware SHA-256 does not match; no patch applied.")
    _require(original[:8] == struct.pack("<II", 0x20017B00, 0x08005441), "Unexpected vector table.")
    for offset, expected in ORIGINAL_SITES.items():
        _require(original[offset:offset + len(expected)] == expected, f"Unexpected instruction at 0x{offset:x}.")
    for offset, expected, _replacement in DASHBOARD_PATCHES:
        _require(original[offset:offset + len(expected)] == expected, f"Unexpected home-screen data at 0x{offset:x}.")


def _fast_helper(original: bytes) -> bytes:
    """Build the snapshot hook; the native decoder is taken from the user's file.

    The copied decoder has only internal relative branches. Its ten PC-relative
    loads all addressed the same channel buffer; replace those with MOV R0,SP.
    Hashes pin both the entire input and this audited block. No disassembler or
    vendor decoder bytes are distributed with this script.
    """
    body = bytearray(original[BODY_START:BODY_END])
    _require(sha256(body) == BODY_SHA256, "The audited USB decoder block does not match.")
    _require(struct.unpack_from("<I", original, SOURCE_POINTER_OFFSET)[0] == SOURCE_POINTER,
             "Unexpected packed-channel pointer.")
    for offset in SOURCE_LOAD_OFFSETS:
        word = struct.unpack_from("<H", body, offset)[0]
        literal = ((FLASH_BASE + BODY_START + offset + 4) & ~3) + (word & 0xFF) * 4
        _require(word & 0xFF00 == 0x4800 and literal == FLASH_BASE + SOURCE_POINTER_OFFSET,
                 "Unexpected PC-relative decoder instruction.")
        struct.pack_into("<H", body, offset, 0x4668)  # MOV r0,sp, flags unchanged.

    address = FLASH_BASE + ORIGINAL_SIZE
    # Preserve r4-r7/LR (20 bytes) plus 28 local bytes: 48 bytes, 8-byte aligned.
    code = bytearray(_halfwords(0xB5F0, 0xB087, 0x4E00, 0x466F))
    code += _halfwords(0xF3EF, 0x8510, 0xB672)  # MRS r5,PRIMASK; CPSID i.
    # Only six loads and six stores are masked; no call, loop or MMIO access.
    for offset in range(0, 20, 4):
        code += _halfwords(0x6800 | ((offset // 4) << 6) | (6 << 3),
                           0x6000 | ((offset // 4) << 6) | (7 << 3))
    code += _halfwords(0x8800 | (10 << 6) | (6 << 3),
                       0x8000 | (10 << 6) | (7 << 3))
    code += _halfwords(0xF385, 0x8810)  # Restore the original PRIMASK, not unconditional enable.
    code += body
    code += _halfwords(0xB007, 0xE8BD, 0x40F0)  # Restore locals and r4-r7/LR.
    code += _branch(address + len(code), FLASH_BASE + BODY_END)
    while (address + len(code)) % 4:
        code += _halfwords(0xBF00)
    literal_address = address + len(code)
    code += struct.pack("<I", SOURCE_POINTER)
    displacement = literal_address - ((address + 8) & ~3)
    _require(0 <= displacement <= 1020 and displacement % 4 == 0, "Literal pool is out of range.")
    struct.pack_into("<H", code, 4, 0x4E00 | (displacement // 4))
    _require(len(code) == FAST_SIZE - ORIGINAL_SIZE, "Unexpected snapshot hook length.")
    return bytes(code)


def build_patch(original: bytes, *, usb_1ms: bool = False, dashboard: str = "original", layout: dict | None = None,
                startup_photo: bytes | None = None,startup_animation: bytes | None = None,startup_player_version: int | None = None) -> bytes:
    """Return a pinned preset or deterministic custom layout from exact stock."""
    from dashboard_fullscreen import THEMES,layout as theme_layout
    if dashboard in THEMES:
        _require(layout is None,'A drift preset has its own fixed layout.')
        return build_patch(original,usb_1ms=usb_1ms,dashboard='custom',layout=theme_layout(dashboard),
                           startup_photo=startup_photo,startup_animation=startup_animation,startup_player_version=startup_player_version)
    _require(dashboard in ("original", "ch1234", "ch123456", "custom"),
             "Dashboard must be 'original', 'ch1234', 'ch123456' or 'custom'.")
    _require(type(usb_1ms) is bool, "USB choice must be a boolean.")
    _require_original(original)
    if startup_photo is not None:
        _require(startup_animation is None and startup_player_version is None,'Choose one startup option.')
        return photo.attach(build_patch(original,usb_1ms=usb_1ms,dashboard=dashboard,layout=layout),startup_photo)
    if startup_animation is not None:
        try:
            return startup.attach(build_patch(original,usb_1ms=usb_1ms,dashboard=dashboard,layout=layout),startup_animation,
                                  player_version=startup_player_version)
        except ValueError as error:
            raise PatchError(str(error)) from error
    _require(startup_player_version is None,'Startup player version requires an animation.')
    if dashboard == "custom":
        try:
            return _build_custom_image(original, usb_1ms=usb_1ms, layout=layout)
        except ValueError as error:
            raise PatchError(str(error)) from error
    _require(layout is None, "A layout is accepted only with --dashboard custom.")
    image = bytearray(original)
    image[0x21B0E] = 0x1C  # PLL multiplier 26 -> 24; native USB selector uses /4.
    if usb_1ms:
        helper = _fast_helper(original)
        image[0x96F23] = 1  # IN bInterval; OUT and report format stay unchanged.
        image[0x2C992:0x2C994] = _halfwords(0x2001)  # vTaskDelay(1).
        # Clear ready BEFORE arming TX, so a quick completion cannot be lost.
        image[0x2C986:0x2C992] = (
            _halfwords(0x2000, 0x4906, 0x7008, 0x2001)
            + _branch(FLASH_BASE + 0x2C98E, FLASH_BASE + 0x2918C, link=True)
        )
        image[BODY_START:BODY_START + 6] = (
            _branch(FLASH_BASE + BODY_START, FLASH_BASE + ORIGINAL_SIZE) + _halfwords(0xBF00)
        )
        image += helper
    if dashboard == "ch1234":
        for offset, _expected, replacement in DASHBOARD_PATCHES:
            image[offset:offset + len(replacement)] = replacement
    elif dashboard == "ch123456":
        try:
            appendix, replacements, _metadata = dashboard_six.build_appendix(original, len(image))
        except ValueError as error:
            raise PatchError(str(error)) from error
        for offset, replacement in replacements.items():
            image[offset:offset + len(replacement)] = replacement
        image += appendix
    expected_size = FAST_SIZE if usb_1ms else ORIGINAL_SIZE
    if dashboard == "ch123456":
        expected_size = FAST_CH123456_SIZE if usb_1ms else CLOCK_CH123456_SIZE
        expected_hash = FAST_CH123456_SHA256 if usb_1ms else CLOCK_CH123456_SHA256
    elif dashboard == "ch1234":
        expected_hash = FAST_CH1234_SHA256 if usb_1ms else CLOCK_CH1234_SHA256
    else:
        expected_hash = FAST_SHA256 if usb_1ms else CLOCK_SHA256
    _require(len(image) == expected_size and sha256(image) == expected_hash,
             "Generated image failed its independent expected-size/hash check; do not use it.")
    return bytes(image)


def _build_custom_image(original: bytes, *, usb_1ms: bool, layout: dict) -> bytes:
    canonical = dashboard_custom.validate_layout(layout)
    image = bytearray(build_patch(original, usb_1ms=usb_1ms))
    appendix, replacements, _metadata = dashboard_custom.build_appendix(original, len(image), canonical)
    for offset, replacement in replacements.items():
        image[offset:offset + len(replacement)] = replacement
    image += appendix
    image += dashboard_custom.make_trailer(canonical, usb_1ms)
    limit=(MAX_CUSTOM_IMAGE_SIZE if canonical['schema']==12 and canonical['wallpaper'] is not None else
           startup.PLAYER_OFFSET-1 if canonical['schema'] in (4,5,7,8,9) else FAST_SIZE+dashboard_custom.MAX_APPENDIX_BYTES)
    _require(len(image) <= limit and FLASH_BASE + len(image) < 0x080F5000,
             "Custom firmware exceeds its bounded application area.")
    return bytes(image)


def _restore_original_bytes(image: bytes) -> bytes:
    original = bytearray(image[:ORIGINAL_SIZE])
    for offset, expected in ORIGINAL_SITES.items():
        original[offset:offset + len(expected)] = expected
    for offset, expected, _replacement in DASHBOARD_PATCHES:
        original[offset:offset + len(expected)] = expected
    for offset, expected in dashboard_six.ORIGINAL_SITES.items():
        original[offset:offset + len(expected)] = expected
    for offset,expected in startup.ORIGINAL_SITES.items():
        original[offset:offset+len(expected)]=expected
    _require_original(original)
    return bytes(original)


def _recognize_custom(image: bytes) -> dict | None:
    if not (ORIGINAL_SIZE < len(image) <= MAX_CUSTOM_IMAGE_SIZE and image.endswith(dashboard_custom.TRAILER_MAGIC)):
        return None
    try:
        layout, fast = dashboard_custom.read_trailer(image)
        original = _restore_original_bytes(image)
        # Metadata is never trusted as a certificate: regenerate ALL code,
        # hooks, stock bytes, USB changes and trailer, and compare byte-for-byte.
        regenerated = _build_custom_image(original, usb_1ms=fast, layout=layout)
        if regenerated != image:
            return None
    except (ValueError, TypeError, struct.error):
        return None
    return {"variant": "clock192-usb1ms-custom" if fast else "clock192-custom", "layout": layout}


def revert_patch(image: bytes) -> bytes:
    """Reconstruct the original FILE from a pinned or fully regenerated output.

    This is not a device rollback or settings backup. It does not access a radio.
    """
    variant = inspect_image(image)
    _require(variant["recognized"] and variant.get("base_variant",variant["variant"]) in (
        "clock192", "clock192-usb1ms", "clock192-ch1234", "clock192-usb1ms-ch1234",
        "clock192-ch123456", "clock192-usb1ms-ch123456", "clock192-custom", "clock192-usb1ms-custom"),
             "Revert accepts only an exact known patched image, including its full appendix.")
    return _restore_original_bytes(image)


def make_manifest(original: bytes, result: bytes, operation: str) -> dict:
    """Portable report: no username, path, serial number or local device details."""
    common = min(len(original), len(result))
    return {
        "schema": 1,
        "tool_version": VERSION,
        "operation": operation,
        "input": inspect_image(original),
        "output": inspect_image(result),
        "changed_existing_bytes": sum(a != b for a, b in zip(original[:common], result[:common])),
        "appended_bytes": max(0, len(result) - len(original)),
        "removed_bytes": max(0, len(original) - len(result)),
        "radio_access": False,
        "flash_performed": False,
        "limitations": list(LIMITS),
    }


def validate_local_path(path: str | os.PathLike, *, output: bool = False) -> Path:
    """Reject device/UNC/ADS spellings before any file-system operation."""
    raw = os.fspath(path)
    _require(isinstance(raw, str) and bool(raw.strip()) and "\0" not in raw, "Invalid local file path.")
    portable = raw.replace("\\", "/")
    _require(not portable.startswith("//"), "UNC and device paths are not accepted.")
    _require(not portable.startswith(("/dev/", "/proc/", "/sys/")), "System device paths are not accepted.")
    drive = PureWindowsPath(raw).drive
    _require(not drive or re.fullmatch(r"[A-Za-z]:", drive) is not None, "Device path is not accepted.")
    parts = portable.split("/")
    for index, part in enumerate(parts):
        if not part or part in (".", ".."):
            continue
        if index == 0 and re.fullmatch(r"[A-Za-z]:", part):
            continue
        _require(":" not in part, "Alternate data streams are not accepted.")
        _require(not any(char in part for char in '<>"|?*'), "Unsupported file-path character.")
        _require(not part.endswith((" ", ".")), "Ambiguous trailing spaces/dots are not accepted.")
        name = part.split(".", 1)[0].upper()
        _require(name not in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
                 and re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", name) is None,
                 "Reserved device name is not accepted.")
    candidate = Path(raw).expanduser()
    _require(candidate.name not in ("", ".", ".."), "A file name is required.")
    return candidate


def _windows_drive_type(root: str) -> int:
    # Read-only OS classification. This does not open a volume or enumerate USB.
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_drive_type = kernel.GetDriveTypeW
    get_drive_type.argtypes = [ctypes.c_wchar_p]
    get_drive_type.restype = ctypes.c_uint
    return int(get_drive_type(root))


def _check_local_volume(path: Path, purpose: str) -> None:
    if IS_WINDOWS:
        root = path.resolve().anchor
        _require(bool(root) and _windows_drive_type(root) == 3,
                 f"{purpose} must be on a local fixed Windows drive, not a removable, network or unknown drive.")


def read_regular_file(path: str | os.PathLike) -> bytes:
    source = validate_local_path(path)
    _check_local_volume(source, "Input")
    before = source.lstat()
    _require(stat.S_ISREG(before.st_mode), "Input must be a regular file, not a device, directory or symlink.")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(source, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode), "Input is not a regular file.")
        _require(info.st_size in {size for _name, size in VARIANTS.values()}
                 or ORIGINAL_SIZE < info.st_size <= MAX_IMAGE_SIZE,
                 "Unexpected file size; input was not read.")
        content = stream.read(MAX_IMAGE_SIZE + 1)
    _require(len(content) == info.st_size, "Input changed while it was being read.")
    return content


def read_layout_file(path: str | os.PathLike) -> dict:
    """Read bounded JSON with the same local regular-file restrictions."""
    source = validate_local_path(path)
    _check_local_volume(source, "Layout")
    _require(stat.S_ISREG(source.lstat().st_mode), "Layout must be a regular file, not a link or device.")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(source, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_size <= dashboard_custom.wallpaper.JSON_LIMIT,
                 "Layout is not a bounded regular JSON file.")
        content = stream.read(dashboard_custom.wallpaper.JSON_LIMIT + 1)
    _require(len(content) == info.st_size, "Layout changed while being read.")
    try:
        return dashboard_custom.parse_layout(content)
    except ValueError as error:
        raise PatchError(str(error)) from error


def write_new_output(path: str | os.PathLike, content: bytes, *, source: str | os.PathLike) -> None:
    output = validate_local_path(path, output=True)
    source_path = validate_local_path(source)
    _require(output.resolve() != source_path.resolve(), "Output must be a separate new file; input is never overwritten.")
    _require(inspect_image(content)["recognized"], "Refusing to write an unrecognized output image.")
    _check_local_volume(output, "Output")
    # Exclusive creation also refuses an existing file, symlink, hardlink or directory.
    with output.open("x+b") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
        stream.seek(0)
        readback = stream.read(MAX_IMAGE_SIZE + 1)
        _require(readback == content, "Output readback failed; the output file must not be used.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = commands.add_parser("inspect", help="Identify a local file without modifying it")
    inspect_parser.add_argument("input")
    for command in ("patch", "revert"):
        sub = commands.add_parser(command)
        sub.add_argument("input")
        sub.add_argument("--output", help="New local output file; an existing path is never overwritten")
        sub.add_argument("--dry-run", action="store_true", help="Validate and calculate hashes without creating a file")
        if command == "patch":
            sub.add_argument("--usb-1ms", action="store_true", help="Also apply the experimental 1 ms USB transport changes")
            sub.add_argument("--dashboard", choices=("original", "ch1234", "ch123456", "custom", "strip_drift", "led_segments", "purple_drift"), default="original",
                             help="Original, CH1-4, CH1-6, or a validated custom grid")
            sub.add_argument("--layout", help="Local layout JSON, required only with --dashboard custom")
    args = parser.parse_args(argv)
    if args.command != "inspect" and not args.dry_run and not args.output:
        parser.error("--output is required unless --dry-run is used")
    if args.command == "patch" and bool(args.layout) != (args.dashboard == "custom"):
        parser.error("--layout and --dashboard custom must be used together")
    try:
        original = read_regular_file(args.input)
        if args.command == "inspect":
            report = inspect_image(original)
            print(json.dumps(report, indent=2))
            return 0 if report["recognized"] else 2
        result = build_patch(original, usb_1ms=args.usb_1ms, dashboard=args.dashboard,
                             layout=dashboard_custom.current_layout(read_layout_file(args.layout)) if args.layout else None) if args.command == "patch" else revert_patch(original)
        report = make_manifest(original, result, args.command)
        report["dry_run"] = args.dry_run
        report["file_written"] = False
        if not args.dry_run:
            write_new_output(args.output, result, source=args.input)
            report["file_written"] = True
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, PatchError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
