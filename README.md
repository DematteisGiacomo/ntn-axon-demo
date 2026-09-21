# NTN + Axon person-detection demo

Two-board demo: **nRF54LM20** runs person detection; **nRF9151** (Asset Tracker Template `ntn_usecase`, Iridium) uploads a **64×64** thumbnail as **4×1 KB** NTN UDP chunks (server reassembles).

## Workspace layout

```text
ntn-axon-demo/
├── README.md
├── common/
├── server/
├── app-person/                 # nRF54 person detection (fork)
├── asset-tracker-template/     # nRF9151 NTN + companion (fork)
├── nrf/
├── nrfxlib/
├── zephyr/
└── …
```

**Setup** (NCS **v3.3.0**, nRF9151 **NTN** modem firmware):

```bash
git clone https://github.com/DematteisGiacomo/ntn-axon-demo.git
cd ntn-axon-demo

git clone https://github.com/DematteisGiacomo/app-axon-person-detection.git app-axon-person-detection
git clone https://github.com/DematteisGiacomo/asset-tracker-template.git asset-tracker-template

cd asset-tracker-template && git checkout ntn_usecase_axon && cd ../
cd app-axon-person-detection && git checkout iridium-demo

west init -l .
west update -o=--depth=1 -n
```

Build and flash from this directory (`west build` / `west flash` as below). Iridium SIM required for field UDP upload.

## Board voltage (Board Configurator)

Use **nRF Connect for Desktop → Board Configurator** on each DK so GPIO/UART levels match (3.3 V). Click **Write config** after changes and reset the board.

| DK | Setting | Value | Why |
|----|---------|-------|-----|
| **nRF54LM20 DK** | **VDD (nPM VOUT1)** | **3.3 V** | ArduCam Mega is 3.3 V logic (`VCC` → `VDDIO`). Companion UART21 uses **P1.14 / P1.23** (see wiring). |
| **nRF9151 DK** | **VDD (nPM VOUT1)** | **3.3 V** | Default is often 1.8 V; UART1 (P0.28/P0.29) must be 3.3 V when wired directly to the nRF54. |

On the nRF9151 DK, pick **SIM Card** (not eSIM) if you use a physical Iridium SIM.

### UART / VCOM (what goes where)

Each board uses **three independent channels** in this demo (logs, companion link, and on the nRF54 also USB for the AI stream). Board Configurator **VCOM** switches only control whether the **interface MCU** bridges a USB serial port to certain UART pins—they are not extra UARTs on the chip.

| Board | Purpose | SoC UART | PC / DK |
|-------|---------|----------|---------|
| **nRF9151** | App logs + shell | **UART0** | **VCOM0** (`att_ntn`, etc.) |
| **nRF9151** | Thumbnail from nRF54 | **UART1** (P0.28 / P0.29) | Same pins as **VCOM1** when bridged—see below |
| **nRF54LM20** | App logs | **UART20** (P1.16 / P1.17) | **Serial Port 1** on IMCU USB (e.g. `…-if02` @ 115200) |
| **nRF54LM20** | Link to nRF9151 | **UART21** (P1.14 / P1.23) | Header only (no VCOM) |
| **nRF54LM20** | AI stream | **USB HS CDC** | Separate USB device (Python viewer) |

**nRF9151 — companion on UART1:** Turn **off** **Connect port VCOM1** (and **VCOM1 HWFC**) while the nRF54 is wired to Arduino **RX/TX** (UART1). Otherwise the interface MCU and the nRF54 both drive the same lines. Keep **VCOM0** on for logs.

**nRF54LM20 — do not mirror the 9151 VCOM1 rule.** Keep **Serial Port 1** bridged to the interface MCU so **UART20** logs reach the PC @ 115200 (in Board Configurator, leave the **VCOM** switch on that routes to UART20—often **VCOM1** on the LM20 DK; confirm by opening the log port after flash). Companion **UART21** uses **P1.14 / P1.23** (not P1.13—reserved for logic-analyzer trace in the stock app). No need to disable VCOM for inter-board wiring. The other VCOM (often **VCOM0** → UART30) is unused by this app—optional to turn off to reduce extra USB serial devices.

Do **not** connect the two boards’ 3.3 V supply pins together—only **GND** and **UART TX/RX**.

## Wiring (3.3 V UART)

| nRF54LM20 | nRF9151 DK |
|-----------|------------|
| **P1.14** TX | **P0.28** RX (Arduino **RX** / UART1) |
| **P1.23** RX (optional; 9151 ACK) | **P0.29** TX (Arduino **TX** / UART1) |
| GND | GND |

Use the DK pin map / schematic for **P1.14** and **P1.23** on the expansion header. Wire the **Arduino serial** pins on the nRF9151 DK. **UARTE21 cannot use P2** on the nRF54LM20.

115200 baud, cross TX/RX.

## Build — nRF54

```bash
cd app-person
west build -b nrf54lm20dk/nrf54lm20b/cpuapp -- \
  -DDTC_OVERLAY_FILE="boards/nrf54lm20dk_nrf54lm20b_cpuapp.overlay;boards/nrf54lm20dk_nrf54lm20b_cpuapp_companion.overlay"
west flash
```

### Aircraft variant (remote airstrip watch)

[`app-axon-aircraft-detection/`](app-axon-aircraft-detection/README.md) swaps the person detector for the MLPerf Tiny ResNet8 CIFAR-10 classifier (from `tiny/benchmark/training/image_classification`) and triggers on the `airplane` class. Same wiring, overlays and companion protocol; the nRF9151 build is unchanged.

```bash
cd app-axon-aircraft-detection
west build -b nrf54lm20dk/nrf54lm20b/cpuapp -- \
  -DDTC_OVERLAY_FILE="boards/nrf54lm20dk_nrf54lm20b_cpuapp.overlay;boards/nrf54lm20dk_nrf54lm20b_cpuapp_companion.overlay"
west flash
```

Decision: `CONFIG_AIRCRAFT_SCORE_THRESHOLD=750` and `CONFIG_AIRCRAFT_MARGIN=300` (lead over runner-up class). Whole-frame classifier: the aircraft must fill much of the view.

Person detect uses **score threshold 0.9** (`CONFIG_SCORE_THRESHOLD=900`). With **`CONFIG_COMPANION_CHUNKED_NTN=y`** (default in `prj.conf` / axon overlay), the nRF54 sends **4 UART frames** per detect; the nRF9151 sends **4 UDP packets** on one NTN session. Match Kconfig on both boards. Debounced default **15 s** in `prj.conf` for bench. Logs: `Companion sent frame … (4096 B in 4 chunks)` and `Companion reassembly complete` on the 9151.

## Build — nRF9151 (Iridium + companion)

NTN modem firmware (`mfw_nrf9151-ntn`) and Iridium SIM required.

```bash
cd asset-tracker-template
west build app -b nrf9151dk/nrf9151/ns -- \
  -DEXTRA_CONF_FILE="overlay-ntn-iridium.conf;overlay-ntn-iridium-axon.conf" \
  -DEXTRA_DTC_OVERLAY_FILE="boards/nrf9151dk_nrf9151_ns_companion.overlay"
west flash
```

Modem trace on UART1 is disabled (`overlay-ntn-iridium-axon.conf`); use **VCOM0** for shell (`att_ntn` commands). Rebuild pristine after changing that overlay: `west build -p ...`.

If boot stops right after TF-M with no app logs, check **merged** config: `CONFIG_NRF_MODEM_LIB_TRACE=n` and `CONFIG_UART_1_ASYNC=n` (UART1 must not be claimed by modem trace while companion uses it).

**Bench without GNSS:** `att_ntn set_gnss_location 63.43 10.39 40.0 0` then press button or wait for companion trigger.

## Local debug (no Iridium)

After the nRF54 sends a detect, the nRF9151 keeps the **last** frame (all 4 chunks) in RAM, even after NTN consumes the pending copy.

**UART-only bench build** (no SIM / sky view needed): add `overlay-companion-bench.conf`. Frames are received, ACKed and kept for the shell, but no NTN upload is triggered, so each new frame replaces the previous one instead of being dropped as "upload in progress".

```bash
cd asset-tracker-template
west build app -b nrf9151dk/nrf9151/ns -d build-bench -- \
  -DEXTRA_CONF_FILE="overlay-ntn-iridium.conf;overlay-ntn-iridium-axon.conf;overlay-companion-bench.conf" \
  -DEXTRA_DTC_OVERLAY_FILE="boards/nrf9151dk_nrf9151_ns_companion.overlay"
west flash -d build-bench
```

Pair it with the nRF54 aircraft app built with `overlay-test-images.conf` (see [`app-axon-aircraft-detection/README.md`](app-axon-aircraft-detection/README.md)) to test the full Axon → UART → nRF9151 path from static images, without a camera.

**Shell (VCOM0 @ 115200):**

```text
att_companion status
att_companion show
att_companion dump
```

`show` draws the received 64×64 thumbnail as ASCII art (contrast stretched, 64 columns × 32 lines) with frame ID and score. `dump` prints one `COMPANION_WIRE … chunk=i/n` line per chunk, each followed by its `COMPANION_HEX…` lines, then `COMPANION_END`.

**PC viewer** (same machine as VCOM0):

```bash
cd server
pip install -r requirements.txt
python3 companion_serial_viewer.py /dev/ttyACM0 --watch --out captures
```

The viewer reassembles the chunks into the full 64×64 image. `--watch` mirrors the log and auto-fetches on each `Companion reassembly complete` / `Companion image pending` / `Companion image received` event. Without `--watch`, run once after `att_companion dump` on the shell (or let the script send `att_companion dump` for you).

## UDP server

On a host with a public IP (open UDP port in firewall):

```bash
cd server
python3 udp_image_server.py --port 4567 --out captures
```

Raw luma files are `*.raw` (dimensions in filename, e.g. `32x32`); metadata in matching `*.txt`.

View the latest capture as PNG (needs `pip install pillow`):

```bash
cd server
python3 view_capture.py --latest --dir captures --show
```

Or convert a specific file: `python3 view_capture.py captures/foo_16x16.raw --scale 16`.

## Protocol

Shared framing: [`common/companion_proto.h`](common/companion_proto.h) — magic `AXF1`, header, CRC32. **`msg_type=2`** chunks: `detect_count`=chunk index, `image_fmt`=chunk total. See [`common/Kconfig.companion`](common/Kconfig.companion). Server: [`server/udp_image_server.py`](server/udp_image_server.py) reassembles chunks; test with `python3 server/test_udp_client.py --chunked`.
