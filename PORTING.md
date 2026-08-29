# Kia Carnival 2025 HEV — Porting Notes

This fork adds **2025 Kia Carnival HEV (CCNC)** support to sunnypilot for the
**comma 4**, on top of the **latest stable release** (`release-mici` =
`v2026.002.002`, commit `6a17f75c`, "sunnypilot v2026.002.002", 2026-08-06).

## Base

- **Base branch:** `release-mici` (`v2026.002.002`) — the latest stable sunnypilot
  release intended for the Comma 4 (C4, codename "mici"). This is the same commit
  `release-tizi` (C3X) points at.
- **Key structural fact:** in this release, `opendbc` and `panda` are **vendored
  in-repo** as subtrees (not git submodules). All vehicle logic therefore lives in
  `opendbc_repo/`; the main openpilot repo required no changes.

## Sources ported

1. **Vehicle support (connectivity + tuning):** [`ccdunder/openpilot`](https://github.com/ccdunder/openpilot),
   branch `kia-carnival-25-sp-dev` (tip `5093009` in its `opendbc` fork). The
   Carnival HEV work is a clean, linear chain of ~15 vehicle-specific commits.
2. **CCNC integration:** only the CCNC pieces required by the Carnival HEV. The
   vehicle is `flags=HyundaiFlags.CCNC`, so the CCNC cluster messaging
   (`CCNC_0x161`/`0x162`) and the associated safety whitelist are part of the port.
3. **BSM + `UNSUPPORTED_LONGITUDINAL`:** [`acidofrain/opendbc`](https://github.com/acidofrain/opendbc),
   branch `kia-carnival-2026-sx` — the 2026 Carnival SX (ICE, HDA2) sibling port.
   Two clean commits folded in: the `ADAS_CMD_50_50ms` BSM-subscription fix and the
   honest `UNSUPPORTED_LONGITUDINAL` platform flag.
4. **CAN FD radar tracks (MRR20):** [`sunnypilot/opendbc` PR #351](https://github.com/sunnypilot/opendbc/pull/351)
   by `johnhihi` — adds `RADAR_TRACK_180`–`184` DBC messages and the `_update_canfd`
   radar parser for the Carnival's Mando MRR20 (0x180 ~50 Hz + 0x181 ~5 Hz), enabling
   lead detection for the future longitudinal path.
5. **Full CCNC cluster UI:** the `create_ccnc` from sunnypilot's `ccnc-port` — the
   "beautiful UI" CCNC feature set: fault-free dash, lane-change-assist (LCA) icons and
   arrows, lane-line curvature + position animation, lane-departure steering-wheel
   vibration (`VIBRATE`), blind-spot indicators, and the nav/SLA/target icons. Requires
   the `FR_CMR_03_50ms` (msg_1b5) camera message; gracefully degrades to the basic
   subset if that message is not present on the Carnival.

### Porting note: flag + scope fixes applied while folding in radar tracks

- **`CANFD_RADAR` flag bit reassigned to `2**28`** — PR #351 used `2**27`, which
  collides with `CCNC` on this release-mici base (PR #351 predates `CCNC` landing on
  `2**27`). Avoided a subtle, hard-to-debug flag collision.
- **Fixed a latent `CAN` NameError** — PR #351's `radarUnavailable` line referenced
  `CAN.ACAN`, but `CAN` is only in scope inside the CAN-FD branch of `_get_params`,
  which would crash classic-CAN Hyundai cars. Re-expressed using the `CANFD_RADAR`
  flag instead (which is only set in the CAN-FD branch).

## Deliberately excluded: LFA2 / angle steering

The Carnival SX/SX-P HDA2 ECU reports `AciPluginSta = 0` — it does **not** support
angle steering (LFA2). LFA2 was confirmed "not supported" on the 2026 Carnival SX HDA2
by `acidofrain`'s reverse-engineering, and sunnypilot's `hkg-angle-steering-2025`
branch targets a *different* platform group (Sorento/Ioniq/Santa Fe angle-steering
variants). The Carnival HDA2 is a **torque-steering** car (`LKAS_ALT` 0x110, ADAS
forwards as LFA). The ~2000-line LFA2 branch was therefore **not** folded in — it is
inapplicable to this vehicle and would only add beta code surface with no benefit.

## What was ported (12 files, all in the vendored opendbc)

| File | Change |
|------|--------|
| `opendbc/car/hyundai/values.py` | `KIA_CARNIVAL_HEV_4TH_GEN` platform (mass 2253, wheelbase 3.09, steerRatio 14.23, `CCNC` flag); `HyundaiFlags.CCNC = 2**27`; `HyundaiSafetyFlags.CCNC = 1024`; steer-delta tune; fuzzy-whitelist entry |
| `opendbc/car/hyundai/interface.py` | `steerActuatorDelay = 0.35`; BSM disabled on Carnival HEV (ADAS-ECU limitation); CCNC safety-param wiring |
| `opendbc/car/hyundai/fingerprints.py` | Carnival HEV `fwdCamera`/`fwdRadar` FW versions + 2024 ICE FW revisions |
| `opendbc/car/fingerprints.py` | `KIA CARNIVAL HYBRID 4TH GEN` migration entry |
| `opendbc/car/hyundai/hyundaicanfd.py` | `create_buttons` ALT_BUTTONS (`CRUISE_BUTTONS_ALT`, `SET_ME_2`); `create_lfahda_cluster` CCNC; `create_ccnc`; Carnival ADRV magic bytes (`SET_ME_9 0x1`, `SET_ME_1C 0x8`, `SET_ME_E1 0x14`, `SET_ME_3A 0x80`) |
| `opendbc/car/hyundai/carstate.py` | CCNC `CCNC_0x161`/`0x162` capture + parser; `USE_ALT_LAMP` blinker detection |
| `opendbc/car/hyundai/carcontroller.py` | `create_ccnc` transmit; cruise-standstill resume for ALT_BUTTONS cars |
| `opendbc/safety/modes/hyundai_canfd.h` | CCNC safety param (`1024`) + `0x161`/`0x162`/`0x7C4`/`0xEA` TX whitelist; ALT_BUTTONS `0x1AA` TX support across all init branches |
| `opendbc/car/torque_data/override.toml` | `KIA_CARNIVAL_HEV_4TH_GEN = [1.95, 1.75, 0.12]` |
| `opendbc/car/tests/routes.py` | test route `6c0069dcd5bbb6c1/00000020--6b95507969` (HDA2) |
| `opendbc/sunnypilot/car/car_list.json` | two Carnival Hybrid 2025 entries |
| `docs/CARS.md` | two Carnival Hybrid 2025 rows |

## Deliberate deviations from the source branch (important)

The goal was a **clean, correct, compilable** result, not a byte-for-byte copy.
Three latent bugs in the `ccdunder` source were corrected rather than propagated:

1. **`values.py` steer-delta typo** — the source set `STEER_DELTA_DOWN` twice
   (`= 4` then `= 6`). The second is clearly `STEER_DELTA_UP = 6`; fixed.
2. **`create_ccnc` duplicate message** — the source appended `CCNC_0x161` twice;
   the second must be `CCNC_0x162`. Fixed.
3. **Undefined DBC signals** — the source referenced `SET_ME_A8`, `SET_ME_2C`,
   `SET_ME_56`, `SET_ME_F7`, `SET_ME_9F`, `SET_ME_10` and message `ADRV_0x38C`
   in Python, but these do not exist in any DBC (generator or generated) in the
   branch — they would raise at packaging time. These appeared to be uncommitted
   local magic bytes. The *valid* DBC-value changes were kept (they are the real
   Carnival tuning); only the phantom signals/messages were dropped. Adding
   correct bit layouts for them would require CAN captures from the car and was
   intentionally left out rather than invented.

## Safety notes

The Carnival HEV is CCNC + camera-SCC + ALT_BUTTONS, so the panda safety model
needed two additions that were missing from the stable base:

- A `HYUNDAI_PARAM_CCNC = 1024` flag and a `hyundai_ccnc` runtime flag, wired from
  `HyundaiSafetyFlags.CCNC` in `interface.py`.
- Whitelisting of the CCNC cluster messages (`0x161`, `0x162`) and the ALT_BUTTONS
  cruise-button message (`0x1AA`) for TX, across every steering/longitudinal branch.

Without these, the panda would block the CCNC HUD messages and/or the alt-button
cruise buttons, and the car would not function.

## Verification performed

- `py_compile` and full `ast.parse` on all 8 modified Python files — clean.
- `car_list.json` parses as valid JSON; `override.toml` parses as valid TOML.
- All `KIA_CARNIVAL_HEV_4TH_GEN` references are consistent across
  values/fingerprints/interface/test-routes/torque-data/car_list.
- Every CCNC signal referenced by `create_ccnc` exists in the generator DBC.
- The safety header is brace/paren-balanced and every added macro/array is
  declared and used exactly once.

A full openpilot build (which generates capnp bindings and compiles the safety
model) requires the Linux build toolchain and was not performed on this host; the
user should run the standard sunnypilot CI/build on the device or in Docker to
confirm, then test on the car.

## Install

Push this branch to a GitHub fork, then on the comma 4:
**Settings → Software → Custom Software → enter the fork URL**
(e.g. `https://github.com/<you>/sunnypilot` with branch
`kia-carnival-2025-hev`), or use the install URL
`installer.comma.ai/<your-username>/sunnypilot` pointing at this branch.
