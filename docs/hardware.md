# PulseScope Hardware Design

Version: 1.0  
Target: ESP32-S3-DevKitC-1 (or custom ESP32-S3 board)

---

## Overview

This document describes the hardware architecture for PulseScope, a 4-channel logic analyzer based on the ESP32-S3 microcontroller.

---

## Block Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           PULSESCOPE HARDWARE                              │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐         │
│    │  CH0     │    │  CH1     │    │  CH2     │    │  CH3     │         │
│    │  SMA/    │    │  SMA/    │    │  SMA/    │    │  SMA/    │         │
│    │  Header  │    │  Header  │    │  Header  │    │  Header  │         │
│    └────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘         │
│         │               │               │               │                │
│         ▼               ▼               ▼               ▼                │
│    ┌──────────────────────────────────────────────────────────┐          │
│    │            INPUT PROTECTION & LEVEL SHIFTING              │          │
│    │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐  │          │
│    │  │Series│ │Clamp │ │Pull- │ │Series│ │Clamp │ │Pull- │  │          │
│    │  │  R   │ │Diodes│ │down R│ │  R   │ │Diodes│ │down R│  │          │
│    │  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘  │          │
│    └──────────────────────────┬──────────────────────────────┘          │
│                               │                                          │
│                               ▼                                          │
│    ┌──────────────────────────────────────────────────────────┐          │
│    │            GPIO MATRIX → I2S0 PARALLEL RX                 │          │
│    │  CH0→GPIO12, CH1→GPIO13, CH2→GPIO14, CH3→GPIO15          │          │
│    │  (I2S0_DATA_IN0..3)                                       │          │
│    └──────────────────────────┬──────────────────────────────┘          │
│                               │                                          │
│                               ▼                                          │
│    ┌──────────────────────────────────────────────────────────┐          │
│    │              ESP32-S3 (WROVER for PSRAM)                  │          │
│    │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────────┐  │          │
│    │  │  CPU0   │  │  CPU1   │  │  SRAM   │  │  PSRAM     │  │          │
│    │  │ 240 MHz │  │ 240 MHz │  │ 512 KB  │  │ 8 MB (opt) │  │          │
│    │  └────┬────┘  └────┬────┘  └────┬────┘  └─────┬──────┘  │          │
│    │       │            │            │             │          │          │
│    │       ▼            ▼            ▼             ▼          │          │
│    │  ┌─────────────────────────────────────────────────┐     │          │
│    │  │ I2S0 (Parallel) → DMA → Ring Buffer → USB CDC   │     │          │
│    │  │ (4-ch, up to 20 MS/s, 256k samples buffered)    │     │          │
│    │  └─────────────────────────────────────────────────┘     │          │
│    │  ┌─────────────────────────────────────────────────┐     │          │
│    │  │ TinyUSB Stack → USB PHY → USB-C                 │     │          │
│    │  └─────────────────────────────────────────────────┘     │          │
│    │  ┌─────────────────────────────────────────────────┐     │          │
│    │  │ Trigger Engine (FreeRTOS task, edge/pulse/pat)  │     │          │
│    │  └─────────────────────────────────────────────────┘     │          │
│    └──────────────────────────────────────────────────────────┘          │
│                               │                                          │
│
│
│                               ▼                                          ││
│    ┌──────────────────────────────────────────────────────────┐          ││
│    │                    USB-C CONNECTOR                         │          ││
│    │  VBUS  D+  D-  GND  (CDC-ACM, 2 Mbps effective)          │          ││
│    └──────────────────────────────────────────────────────────┘          │ │
│                                                                         │  │
└─────────────────────────────────────────────────────────────────────────┘  │
```

---

## Input Front-End

### Per-Channel Circuit

```
                          3.3V
                           │
                           │
                       ┌───┴───┐
                       │ Clamp │
                       │Diode  │  (BAT54S or similar)
                       └───┬───┘
                           │
                    ┌──────┴──────┐
                    │   100 Ω     │  Series resistor
                    │  (0603)     │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │   100 kΩ    │  Pull-down to GND
                    │  (0603)     │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │  GPIO12-15  │  → I2S0_DATA_IN0..3
                    │  (Input)    │
                    └─────────────┘
```

**Purpose of each component:**
- **Series 100 Ω**: Limits current into GPIO, provides ESD protection
- **Clamp diodes (BAT54S dual Schottky)**: Clamp voltage to 3.3V + 0.3V / -0.3V, protects against >3.3V input
- **100 kΩ pull-down**: Defines default state when input is floating; prevents false triggers

### Voltage Thresholds

| Parameter | Value |
|-----------|-------|
| Input High (VIH) | ≥ 2.0 V (typical 1.65 V) |
| Input Low (VIL) | ≤ 0.8 V |
| Maximum Input | 5.5 V (with clamp diodes) |
| Input Impedance | ~100 kΩ (DC) |

**Note**: For 5V-tolerant inputs, the clamp diodes are essential. Without them, 5V signals can damage the ESP32-S3 GPIOs.

### Connector Options

| Connector | Use Case | Pros | Cons |
|-----------|----------|------|------|
| 0.1" Header (2×5) | Breadboard/prototyping | Cheap, standard | Not keyed, fragile |
| SMA (PCB edge) | High-frequency, production | Rugged, shielded | Expensive, larger |
| Micro-Coaxial (MHV) | Very high freq | Best signal integrity | Very expensive |
| 2×5 Box Header + Ribbon | General purpose | Keyed, secure | Cable required |

**Recommended for v1.0**: 0.1" header + optional SMA footprints (unpopulated)

---

## Clock Source

### Internal PLL (Default)
- **Source**: ESP32-S3 APLL (Audio PLL)
- **Range**: 1 KHz – 20 MHz (software configurable)
- **Jitter**: < 1 ns RMS
- **Accuracy**: ±50 ppm (crystal tolerance)

### External Clock (Optional)
- **Input**: GPIO4 (I2S0_CLK_IN)
- **Range**: DC – 40 MHz
- **Signal**: 3.3V CMOS, 50% duty cycle preferred
- **Use Case**: Synchronous capture with external clock, multi-board sync

---

## Power

### Supply Requirements

| Rail | Current (Typical) | Current (Max) |
|------|-------------------|---------------|
| 3.3V | 300 mA | 500 mA |
| USB VBUS | 100 mA | 250 mA |

### Power Architecture
```
USB VBUS (5V)
    │
    ├──► USB-C Connector (with ESD protection)
    │
    ├──► LDO (3.3V, 1A) ──► ESP32-S3 VDD_3V3
    │
    └──► VBUS sense (for USB power negotiation)
```

### ESP32-S3 Power Pins
- All VDD_3V3 pins connected to 3.3V rail (with 0.1 µF + 10 µF bypass per pin group)
- VDD_SPI tied to 3.3V (for internal flash, or external flash if used)
- CHIP_PU with 10 kΩ pull-up + 0.1 µF to GND + reset button

---

## Memory Options

### Without PSRAM (ESP32-S3-WROOM)
- **SRAM**: 512 KB (400 KB usable)
- **Max capture buffer**: ~200 KB (100k 4-ch samples = 10 ms @ 10 MS/s)
- **Cost**: Lower

### With PSRAM (ESP32-S3-WROVER, Recommended)
- **SRAM**: 512 KB + 8 MB PSRAM
- **Max capture buffer**: 4 MB (2M 4-ch samples = 200 ms @ 10 MS/s)
- **Cost**: ~$1-2 more
- **Essential for**: Long captures, high sample rates, protocol decoders

**Recommendation**: Use WROVER for production; WROOM acceptable for prototypes.

---

## PCB Design Guidelines

### Layer Stack (4-layer minimum)
| Layer | Purpose |
|-------|---------|
| Top | Signals, connectors, components |
| Inner 1 | GND plane (unbroken under GPIO traces) |
| Inner 2 | 3.3V power plane |
| Bottom | Signals, components |

### Critical Routing

| Signal | Requirement |
|--------|-------------|
| GPIO12-15 (CH0-3) | Keep short, avoid vias, length-matched (±5mm), GND guard traces |
| USB D+/D- | 90 Ω differential, length-matched, no vias if possible |
| 3.3V supply | Wide pours, multiple vias to power plane |
| GND | Unbroken plane under all fast signals |

### EMC Considerations
- Place clamp diodes as close to connector as possible
- Series resistors at connector, not near MCU
- Ferrite bead on USB VBUS input
- Common-mode choke on USB D+/D- optional for certification

---

## BOM (Bill of Materials)

### Minimal BOM (v1.0)

| Qty | Ref | Value | Package | Description |
|-----|-----|-------|---------|-------------|
| 1 | U1 | ESP32-S3-WROVER | Module | MCU with 8 MB PSRAM |
| 1 | U2 | CH340K / CP2102N | QFN | USB-UART (for debug, optional) |
| 1 | D1 | BAT54S | SOT-23 | Dual clamp diode (CH0/1) |
| 1 | D2 | BAT54S | SOT-23 | Dual clamp diode (CH2/3) |
| 8 | R1-R8 | 100 Ω | 0603 | Series resistors |
| 4 | R9-R12 | 100 kΩ | 0603 | Pull-downs |
| 1 | R13 | 10 kΩ | 0603 | EN pull-up |
| 1 | C1 | 10 µF | 0805 | Bulk decoupling |
| 10 | C2-C11 | 100 nF | 0402 | Bypass caps |
| 1 | C12 | 1 µF | 0603 | 3.3V bulk |
| 1 | FB1 | 600 Ω @100MHz | 0603 | Ferrite on VBUS |
| 1 | J1 | USB-C | SMT | USB-C receptacle |
| 1 | J2 | 0.1" Header | 2×5 | Logic input header |
| 1 | SW1 | Tactile | 6×6 | Reset button |

### Optional / Future
| Ref | Value | Purpose |
|-----|-------|---------|
| SMA1-4 | SMA Edge | High-freq connectors |
| U3 | LDO 3.3V/1A | If not using module regulator |
| Y1 | 40 MHz XO | External clock input |

---

## Firmware Pin Map

| Logical | GPIO | I2S Signal | Function |
|---------|------|------------|----------|
| CH0 | 12 | I2S0_DATA_IN0 | Logic input 0 |
| CH1 | 13 | I2S0_DATA_IN1 | Logic input 1 |
| CH2 | 14 | I2S0_DATA_IN2 | Logic input 2 |
| CH3 | 15 | I2S0_DATA_IN3 | Logic input 3 |
| CLK_IN | 4 | I2S0_CLK_IN | External clock (optional) |
| CLK_OUT | 5 | I2S0_CLK_OUT | Clock output (for sync) |
| USB_DP | 19 | USB PHY | USB D+ |
| USB_DM | 20 | USB PHY | USB D- |
| UART_TX | 43 | UART0 | Debug output |
| UART_RX | 44 | UART0 | Debug input |
| EN | - | CHIP_PU | Reset (active low) |
| BOOT | 0 | GPIO0 | Boot mode (hold low for download) |

---

## Mechanical

### Board Outline
- Size: 50 × 30 mm (2-layer) or 45 × 25 mm (4-layer)
- Mounting holes: 2× M2.5, diagonal corners
- USB-C on short edge
- Logic header on opposite edge

### Enclosure (Optional)
- 3D printed case: 60 × 35 × 15 mm
- USB-C and logic header cutouts
- Label: "PulseScope v1.0 - CH0/1/2/3"

---

## Testing & Validation

### Electrical Tests
1. **Continuity**: All signal paths from header to MCU
2. **Resistance**: 100 Ω ±5% on series Rs; 100 kΩ ±1% on pull-downs
3. **Diode clamp**: Forward drop ~0.3V, reverse leakage <1 µA
4. **3.3V rail**: No shorts, clean startup
5. **USB enumeration**: Device appears as CDC-ACM

### Functional Tests
1. **Signal integrity**: 10 MHz square wave on CH0, verify clean capture
2. **Crosstalk**: Toggle CH0 at 20 MHz, measure bleed on CH1-3 (< 50 mV)
3. **Sample rate accuracy**: 10 MS/s ±50 ppm
4. **Trigger latency**: Edge trigger fires within 1 sample period
5. **USB throughput**: Sustained 2 Mbps data streaming

### EMI/EMC (Pre-compliance)
- Radiated emissions < 30 MHz: < 40 dBµV/m
- Conducted emissions on USB: < CISPR 22 Class B

---

## Revision History

| Rev | Date | Changes |
|-----|------|---------|
| 1.0 | 2024 | Initial hardware specification |

---

## References

- [ESP32-S3 Technical Reference Manual](https://www.espressif.com/sites/default/files/documentation/esp32-s3_technical_reference_manual_en.pdf)
- [ESP32-S3 Datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_en.pdf)
- [I2S Parallel Mode Application Note](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/i2s.html)
- [USB 2.0 Specification](https://www.usb.org/document-library/usb-20-specification)