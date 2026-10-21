# Sensor notes

Findings from decoding the factory TPMS sensors on a 2013 Scion FR-S with rtl_433.

## Hardware

- Sensors: BH Sens RDE057V21 (OE-style replacement), 315 MHz
- Receiver: RTL-SDR Blog V3 + telescopic antenna, inside the cabin

## How rtl_433 sees them

- Decoder: model **"Toyota"**, type TPMS, FSK, ~315.0 MHz
- Fields: `id` (8-digit hex), `pressure_PSI` (0.25 psi steps), `temperature_C`
  (whole °C, air temperature inside the tire), `status`, `mic: CRC`
- No battery field
- Every transmission repeats 3–4 times within ~1–2 s, so dedupe before logging
- Neighbouring cars with the same sensor type show up too, so filter by ID

## Status values and timing

| `status` | Meaning | Interval per tire |
|---|---|---|
| 128 (0x80) | Parked / normal | ~90–100 s |
| 131 (0x83) | Driving | ~64 s, very regular |
| 132 (0x84) | Pressure change detected (bit 0x04) | ~18 s for several minutes |

- When a sensor switches mode (e.g. 128 → 131), it sends one extra transmission
  ~16–17 s later.
- Missed transmissions show up as 96–128 s gaps; about 1 in 70 were missed on an
  18-minute drive.
- A quick drop of a few psi (pressing the valve core) forces a transmission. This is
  how each ID was matched to its wheel.

## Signal

- RSSI ≈ +1 dB (strong), SNR mostly 7–10 dB, occasionally 16–18 dB.
- Ideas for better SNR: USB extension cable to move the dongle away from the laptop,
  antenna ≈ 24 cm (quarter wave at 315 MHz), try a fixed gain (`-g`).

## Example: warm-up on a street drive

18 minutes, ~5 °C morning (`samples/2026-10-21_morning_drive.csv`):

- Pressure rose ~3.5 psi (≈ 29.5 → 33 psi)
- Air temperature in the tires rose from 5–7 °C to 22 °C

## Limits of TPMS for track use

About one update per minute per tire is fine for pressure trends and leak alarms,
but too slow to follow tire temperatures through a lap. Real-time tread temperatures
need separate IR sensors.
