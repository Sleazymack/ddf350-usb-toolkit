---
name: Experimental USB issue
about: Report an observed problem with clear firmware and test context
title: "[USB] "
labels: bug
---

## Setup

- Hardware revision:
- Patcher/tool version:
- Original firmware version and SHA-256:
- Patched output SHA-256 and variant reported by the patcher:
- Dashboard choice (`original` / `ch1234` / `ch123456` / `custom`):
- Custom layout JSON (if applicable; no personal paths or data):
- Entry point (desktop executable / Python desktop / command line):
- Requested USB interval (20 ms / 1 ms):
- OS and Python version:
- Selected model mode (Normal / Fast, checked on the transmitter):
- Power source and USB connection sequence:

## Steps and observations

Describe the order of events and the time until the problem appears.

- Does USB stop sending reports?
- Do the transmitter screen and buttons still respond?
- Does it happen while navigating, while idle in a menu, or at home?
- Does a complete power restart restore operation?
- Is the issue reproducible, and how many times was it tested?
- For a display issue, which channel row, value or bar differs from the selected dashboard?

## Sanitized measurements

Give duration, report count, rate, interval percentiles/max, invalid reports and local logging losses if available. Separate observed facts from suspected causes.

Do not attach vendor firmware, generated firmware, flash dumps, private serial numbers, credentials, or unredacted host paths. This preview does not supply a general-purpose installation method.
