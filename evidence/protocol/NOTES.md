# WG9S static protocol findings

Status: **identity and configuration reads verified on a WG9S host**. The
first successful capture is `tests/fixtures/wg9s-read.json`. It reports CID=13,
MID=7, device type=2, 1000 Hz polling, five stages and active stage 3 (1200 DPI).
Writes and battery remain unverified. Tests also use synthetic peers and
instruction-derived expected packets. No Windows USB captures exist.
No vendor executable or library was executed.

## Inputs and reproducibility

Official installer: `Kanata_S_Wireless_WG9S_Software_V1.0.0.42_24081600.exe`

SHA-256: `fe868bc22604b7b32b584ef3907d4906659d0bd95146112861daf50cf59089c5`

The installer uses Inno Setup 6.1.0. `7z` and `bsdtar` cannot open it here.
`tools/extract_vendor.py` decodes the pinned LZMA stream and reverses the Inno
executable filter for its first file. The file is a managed .NET application.
A plain LZMA extraction leaves executable transformations in place and produces
invalid IL. A standard LZMA BCJ reversal only partially repairs it; neither is
suitable for analysis. The final extractor uses the actual Inno filter format.

Filter reference: [innoextract executable decoder](https://github.com/dscharrer/innoextract/blob/master/src/stream/exefilter.hpp).
This tool is deliberately pinned to this installer hash, not a general-purpose
archive extractor. File metadata/checksums from the Inno directory are not parsed.

`tools/ildump` uses Mono.Cecil to read IL and extract embedded resources without
loading or executing the application. Its `CecilPath` MSBuild property can select
a local Mono.Cecil assembly. Generated output stays in ignored `vendor/`.

Reproduce:

```bash
python3 tools/extract_vendor.py
dotnet run --project tools/ildump -- \
  vendor/extracted/MouseDriver.exe vendor/resources-clean \
  > vendor/application-clean.il
objdump -d -Mintel vendor/resources-clean/costura64.hidusb.dll \
  > vendor/hidusb-clean.asm
```

The application DLL resources include `costura64.hidusb.dll` and
`costura32.hidusb32.dll`. Addresses below refer to the x64 DLL with image base
`0x180000000`; use the corrected extraction, not intermediate research files.

The plain configuration following the first file at solid-stream offset 5318144
contains WG9S-specific settings. Decoded vendor/product strings identify vendor
`3554`, mouse PID `f500`, dongle PID `f501`. Sensor is `3311`. CID is **decimal 13**
(the managed parser uses `Int32.Parse`, not hexadecimal); MID is 7. Interface is
1. DPIMaxGrade is 5. Allowed DPI ranges are 50-10000 step 50, and 10100-12000
step 100 with extension `0x22`. The physical six buttons map to indices
0,1,2,3,4,5, with Back at 3 and Forward at 4. The observed Linux receiver name
is generic; software checks CID/MID before accessing configuration.

## Report framing

17 bytes including report ID:

| Byte | Meaning |
| --- | --- |
| 0 | Report ID `08` |
| 1 | Command |
| 2 | Status/reserved; requests initialize to zero |
| 3-4 | Configuration address, big endian |
| 5 | Length |
| 6-15 | Up to 10 payload bytes, zero-padded in requests |
| 16 | `(0x55 - sum(bytes 0..15)) & 0xff` |

Checksum implementation: VA `0x18000d2b0`.
Read configuration: VA `0x18000db80`, command `08`, at most 10 bytes per request.
Write configuration: VA `0x180005e00`, command `07`.
Native transport: VA `0x18000acb0` uses Windows `WriteFile` and `ReadFile` with
17-byte reports, rather than HID feature reports. Its IAT entries at
`0x1800180a8` and `0x1800180b0` identify those calls.

The native acknowledgement handler at `0x18000f610`, notably `0x18000f868`,
compares a write response to the complete outgoing report. The implementation
requires exact write echo plus an independent configuration readback. Reads
check report checksum, command, address and length. It intentionally does not
interpret unestablished response status codes as success/failure enums.

## Identity and battery

`GetDeviceInfo` at `0x18000af90` sends command `01`, length 8, four random bytes
at payload positions 0..3; the reply contains CID/MID/device type at report
positions 10,11,12. This establishes vendor model identity; it is not a claim
of cryptographic authentication. Only CID=13 and MID=7 are accepted.

Battery request: `0x18000e040`, command `04`, length zero. Battery parser at
`0x180005570` reads level, charging byte, and a big endian 16-bit voltage from
the response payload. The app does not replicate the vendor battery smoothing
or calibration routines; unavailable/unknown data displays as a dash.

## Configuration records

The first 192 configuration bytes include the following records. Each stored
record ends with the same `0x55 - sum(payload)` checksum, independent of the
outer USB packet checksum. Invalid records stop loading instead of substituting
the Windows library's defaults.

| Address | Payload | Evidence |
| --- | --- | --- |
| `00` | Polling rate code (1 byte) | `0x180005e5f` onward |
| `02` | Number of DPI stages (1 byte), preserved | `0x180005ee1` onward |
| `04` | Active stage, zero-based (1 byte) | `0x180005f9e` onward |
| `0c + 4*i` | DPI X code, Y code, extension | parser `0x180005a77`; writer `0x1800068f6` onward |
| `60 + 4*i` | Button class, param1, param2 | parser `0x180005c11`; writer `0x180006fe4` onward |

Polling codes come from managed `DriverLib.REPORT_RATE`: 1000 Hz=1, 500 Hz=2,
250 Hz=4, 125 Hz=8. Generic library codes for 2K/4K are not exposed for WG9S.

DPI numeric lookup values in `kanata/data/sensor3311.json` were extracted from
the bundled `SENSOR_3311_DPI_*` definitions. The values are irregular: DPI cannot
be encoded with a simple division formula. The managed
`DPIControl.ValueToDPI` at RVA `0x40d94` halves the requested DPI and sets
extension `0x22` above 10000; it uses the lookup when the sensor's Discord flag
indicates a discrete table. Existing asymmetric X/Y values remain untouched
unless the stage is edited.

Basic button class 1 uses bit masks: Left=1, Right=2, Middle=4, Back=8, Forward=16.
Class 2 uses DPI Cycle=1, Up=2, Down=3. Class 0 disables a button.
Managed `KeyFunMapDriver.SetMouseKey` RVA `0x5263` and `SetChangeDPIKey` RVA
`0x527b` establish these payloads. Other button classes, macro/shortcut data,
lighting records and advanced sensor settings are left unchanged.

## Hardware validation

The captured host read succeeded with the udev access rule installed and applied.
It is replayed in the test suite. Configuration writes have not been captured. Validate on the
host with `./kanata-studio --read`, then inspect the resulting configuration
and transaction log. Initial writes should change one setting at a time, with
readback and observable mouse behavior checked, followed by restoration.
Replug persistence, wireless sleep/wake and wired/receiver behavior remain
untested. Additional initialization or timing requirements may emerge.


## Macro support

The implemented macro subset was traced from the corrected x64 DLL using REA
and objdump. Macro reads/writes and actual playback are **not yet verified on
hardware**; the existing captured read covers only the first 192 bytes.

- `MacroKeyToBuffer`, VA `0x180007b70`, and its reverse at `0x180007c50` encode
  a macro slot. The update routine at `0x1800073c5` uses flash base `0x300`,
  384-byte stride, and writes the used prefix in chunks of at most ten bytes.
  The parser at `0x180005bfa` advances the same flash stride for 16 slots,
  establishing the 6912-byte configuration map boundary.
- Offset 0: name length, followed by up to 30 name bytes at offsets 1-30. The
  library's SetMacroName (managed RVA `0x5348`) accepts fewer than 30 characters
  and uses the Windows default ANSI encoding. New Linux names are limited to
  printable ASCII for a portable subset. Unused name bytes are filled with FF,
  as in the vendor update routine's initialized output buffer.
- Offset 31: event count, 2-70. Each event occupies five bytes from offset 32:
  `(state_flags | type), value_low, value_high, delay_high, delay_low`.
  Key down flag is `0x80`, key up is `0x40`, and no-transition is zero.
  The event type occupies the low nibble. `HID_CODE_TYPE` in the managed code
  defines modifier=0, keyboard=1, media=2, power=3, mouse=4, motion=5.
- The checksum byte is at offset `32 + 5*count`, calculated over bytes
  `[31, 32 + 5*count)`. Name bytes are excluded. A maximum-length macro uses
  383 of the 384 available bytes. Unused trailing bytes are preserved.
- Delay is **after** each event: the vendor AddMacroKey (managed RVA `0x53bc`)
  writes the newly observed delay into the previous event. The serializer
  stores it big endian; the two-byte key value is little endian.
- `CustomKeyFunction.UpdateMacro` (managed RVA `0x3bf3c`) binds button index i
  with `(type=6, param1=i, param2=CycleTimes)` and copies the macro to slot i.
  This shows that param1 is a slot index, not a playback mode. Existing bindings
  to other valid slots are read for editing; a replacement uses the target
  button's own slot without writing the source slot.
- `FormMain.customButton_Save_Click` (managed RVA `0x1c088`) maps repeat count
  directly into CycleTimes. Values 253, 254, 255 mean until this button pressed,
  until key released, and until a key pressed, respectively. The GUI exposes
  those separately from finite repeat counts 1-252.

New macro assignments require a full raw snapshot of their target slot. The
write planner emits macro chunks before the button record; the transport then
requires echo acknowledgement and readback for each. Stale macro baselines
abort before any writes. Existing shortcut/macro regions are not rewritten
when an ordinary polling/DPI setting changes. Tests cover constructed macro
vectors, maximum counts, checksum corruption, key release balancing, readback,
stale data, partial write failure, GUI staging and focused recording.
