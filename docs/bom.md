# Bill of Materials

Architecture: an ESP32 CAN node reads engine data from the OBD port and sends it over
Wi-Fi to a Raspberry Pi 3 B+. The Pi also reads the tire sensors with an RTL-SDR, logs
everything, runs a Wi-Fi hotspot and serves the dashboard. Any device with a browser
shows it; a 7" Android tablet on the dash is the main display.

```
FR-S OBD ─→ splitter ─┬─→ Dragy OBD
                      └─→ OBD pigtail ─→ T-CAN485 (ESP32) ── Wi-Fi ──┐
                                                                     ▼
RTL-SDR ─── USB ───────────────────────────────────────────→ Raspberry Pi 3 B+ ── Wi-Fi ──→ tablet / phone
```

Prices are CAD as listed on 2026-10-21, before tax and shipping unless noted. *est.* = estimate.

## Already owned

| Item | Role |
|---|---|
| RTL-SDR Blog V3 + telescopic antenna | Receives the 315 MHz tire sensors |
| Dragy OBD | Stays on the OBD port via the splitter |
| Laptop | Development, flashing, testing |

## 1. Engine data node

| # | Item | Source | Price |
|---|---|---|---|
| 1 | LILYGO T-CAN485 ESP32 board (+$15 shipping, arrives Nov 2–6) | [Amazon.ca](https://www.amazon.ca/dp/B0BNQ4KXTX) | $23.23 |
| 2 | bbfly-A9 OBD2 splitter, 1 male → 2 female, flat, 60 cm | [Amazon.ca](https://www.amazon.ca/dp/B0711LGRGQ) | $17.90 |
| 3 | CERRXIAN OBD2 16-pin male → open pigtail, 1.5 m | [Amazon.ca](https://www.amazon.ca/dp/B0CXHLG31Q) | $16.99 |
| 4 | Anker 320 24W dual USB-A car charger (powers the ESP32 and the Pi) | [Amazon.ca](https://www.amazon.ca/dp/B07PGT7LSR) | $14.69 |
| 5 | etguuds USB-A → USB-C cable, 1 ft, 2-pack (power + flashing) | [Amazon.ca](https://www.amazon.ca/dp/B0BVQ6CQX7) | $10.99 |

Wiring (pigtail colours per listing; verify with a multimeter): pin 6 green → CAN H,
pin 14 brown/white → CAN L, pin 5 yellow → GND. Leave the board's 120 Ω termination off.

## 2. Raspberry Pi hub

| # | Item | Source | Price |
|---|---|---|---|
| 6 | Raspberry Pi 3 Model B+ | [PiShop.ca](https://www.pishop.ca/product/raspberry-pi-3-model-b-plus/) | $57.95 |
| 7 | Flirc Raspberry Pi 3B case, silver: aluminium body is the heatsink (thermal pad included), fanless | [flirc.tv](https://flirc.tv/products/flirc-raspberrypi3b-silver?variant=43085036290280) | US$16.95 (~CA$24 *est.*) + shipping |
| 8 | Patriot LX 32 GB microSDHC, Class 10 / U1 (not high-endurance; keep a backup image) | [Amazon.ca](https://www.amazon.ca/dp/B08KSSXKYR) | $17.29 |
| 9 | Short, thick micro-USB cable (≤ 50 cm, 2.4 A+ rated): Anker → Pi | — | ~$8–10 *est.* |
| 10 | Short USB extension, 15–30 cm: keeps the RTL-SDR away from the Pi's electrical noise | — | ~$6–8 *est.* |

## 3. Display and mounting

| # | Item | Source | Price |
|---|---|---|---|
| 11 | onn. 7" Android tablet, 1024×600, Android 11 Go, 2 GB / 16 GB, USB-C (open box, sold by Deals Masters) | [Best Buy](https://www.bestbuy.ca/en-ca/product/open-box-onn-7-inch-1024x600-lcd-touchscreen-2-0-ghz-quad-core-processor-android-tablet/16472949) | $47.95 |
| 12 | Tablet mount: RAM X-Grip for 7–8" tablets + arm + base (no-drill or bolted) | — | ~$80–120 *est.* |
| 13 | Tablet power: a third USB port (the Anker's two go to the ESP32 and Pi), plus a USB-C cable | — | $0–15 *est.* |
| 14 | Velcro + zip ties | — | ~$10 *est.* |

## Optional / later

| Item | Notes | Price |
|---|---|---|
| Pi shutdown add-on (a small battery board) | Clean shutdown when the car turns off | ~$25–40 *est.* |
| IR tread temperature sensors (MLX90614 / MLX90640) | Tire surface temps | TBD |

## Totals

| Group | Cost |
|---|---|
| 1. Engine data node | $83.80 + $15 shipping ≈ **$111.64** with 13% HST |
| 2. Pi hub | ≈ $113–117 before tax |
| 3. Display and mounting | ≈ $138–193 before tax |
| **Total** | **≈ $390–460** with tax (excluding PiShop, Flirc and Best Buy shipping) |
