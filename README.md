# sunnypilot — Kia Carnival 2025 HEV (CCNC) fork

A [sunnypilot](https://github.com/sunnypilot/sunnypilot) fork adding **2025 Kia
Carnival HEV (CCNC)** support for the **comma 4**, built on the latest stable
sunnypilot release (`release-mici` = `v2026.002.002`).

## What this is

- **Base:** sunnypilot `release-mici` (v2026.002.002) — the latest stable release for
  the comma 4 (C4).
- **Vehicle:** 2025 Kia Carnival Hybrid, **SX trim with HDA II**, Q harness.
  See [PORTING.md](PORTING.md) for the full engineering notes.

## What's included (vs. stock sunnypilot)

- `KIA_CARNIVAL_HEV_4TH_GEN` — Carnival Hybrid 2025 platform (CCNC) + fingerprints
- CCNC cluster messaging (`CCNC_0x161/0x162`) and panda safety whitelist
- `CANFD_ALT_BUTTONS` (0x1AA) support for the Carnival HDA2 button architecture
- Full CCNC cluster UI — lane-change-assist icons, lane-line curvature/animation,
  lane-departure vibration, fault-free dash
- Mando MRR20 CAN-FD radar tracks (0x180–0x184) for lead detection
- Blind-spot monitoring (BSM) fix
- Intelligent Cruise Button Management (ICBM) + Speed Limit Assist for ALT_BUTTONS cars

## What's intentionally NOT included

- **Longitudinal control** — marked `UNSUPPORTED_LONGITUDINAL` (unvalidated on this
  vehicle; plumbing is in place but disabled so the car boots clean with no errors).
- **LFA2 / angle steering** — the Carnival SX/SX-P HDA2 ECU reports `AciPluginSta=0`
  (no angle steering); this is a torque-steering car.

## Install

On the comma 4: **Settings → Software → Custom Software**, enter:

```
installer.comma.ai/maxwelltollefson/sunnypilot
```

then select branch `kia-carnival-2025-hev`.

## Status & testing

This port compiles and passes static checks, but **several behaviors are unverified
against a real car** (sign-reading, radar scaling, ICBM button latching, CCNC UI
rendering). See [VALIDATION.md](VALIDATION.md) for the exact checklist to work through
on the first logged drive.

⚠️ This is experimental ADAS software. Always keep your hands on the wheel and be
ready to take over at any time. The stock AEB/FCW safety systems remain active.
