# Validation Checklist — Kia Carnival 2025 HEV (CCNC) fork

Run through this on your **first logged drive** after the comma 4 returns from service.
Each item confirms one thing that could not be verified without the car. Work top to
bottom; the highest-value checks are first.

## Before you drive

- [ ] Install via `installer.comma.ai/maxwelltollefson/sunnypilot` → branch
      `kia-carnival-2025-hev`.
- [ ] Confirm the car **fingerprints correctly**: on the device, check it identifies as
      `Kia Carnival Hybrid 2025` / `Kia Carnival Hybrid (with HDA II) 2025` — *not* a
      generic "dashcam only" or a CAN/CABLING error. If it mis-identifies, stop and grab
      the fingerprint log before driving.
- [ ] Enable **"Record and Upload Driver Camera"** + **route upload** so logs are
      preserved (see the sunnypilot "Share a Route" guide).

## Drive 1 — core connectivity & cluster (the essentials)

- [ ] **Lateral / steering works** — engage LKA/LFA and confirm the car steers (this is
      the torque-based `LKAS_ALT` 0x110 path; it should feel like stock HDA2 or better).
- [ ] **No boot errors / on-screen faults** — no "check cabling", "CAN signal" errors, no
      unexpected disengages. (`UNSUPPORTED_LONGITUDINAL` means longitudinal is hidden, so
      you should see *no* longitudinal options — that's expected, not a bug.)
- [ ] **CCNC cluster UI renders** — lane lines, LFA icon, set-speed, and (if supported)
      lane-change-assist arrows + curvature animation appear on the cluster.
- [ ] **Blind-spot (BSM) indicators** light up when a car is alongside.

## Drive 2 — the two "workaround" capabilities

- [ ] **Speed-limit sign reading** (`0x1fa`): drive past a posted-speed-limit sign and
      note whether the HUD shows a *camera* speed-limit badge. This tells us if the
      Carnival camera emits `0x1fa` (sign reading) or only map data works.
- [ ] **ICBM / Speed Limit Assist**: enable *Settings → Cruise → Intelligent Cruise
      Button Management*. Drive toward a lower speed zone and confirm the **set-speed
      actually steps down** (it'll be coarse, ~1 mph per ~0.2 s, stepping the stock ACC).
      This is the critical "does stock ACC latch synthetic 0x1AA presses?" question.

## Drive 3 — longitudinal data capture (the big one)

This is the single most valuable thing you can produce for yourself *and* the community
(it unblocks true longitudinal on this car).

- [ ] Record a **20–30 min route** that includes: engage/disengage several times,
      stop-and-go in traffic behind a lead car, and a couple of ACC accel/decel events.
- [ ] Confirm the route has **full rlogs uploaded** (rlogs, not just qlogs) and is
      **preserved + public** in comma Connect.
- [ ] Note the **MRR20 radar tracks** — on the UI, confirm the radar plot shows lead
      vehicles (validates the 0x180/0x184 signal scaling I ported from PR #351).

## Drive 4 — corner/side-radar capture (unlocks Tier 2 autonomous pass)

This specifically targets the rear-lateral "is a car closing from behind" signal that
would let the Auto-Passing Suggest feature go from *suggest* to *autonomous*.

- [ ] Drive on a multi-lane road with cars **passing you / alongside you**, and a few
      moments where a car closes on you from behind in the adjacent lane.
- [ ] In the rlog, check whether the Carnival transmits a Mando-style corner-radar
      point stream — traffic on **`0x100`/`0x200`/`0x101`/`0x201`** (the decoded
      EV6/Ioniq 6 format; see `docs/AutoPassingSuggest_Tier1.md` → "Prior art").
- [ ] If those addresses are empty, look for a CAN-FD message from the `0x7b7`
      corner-radar ECU carrying a repeating **distance + relative-velocity + azimuth**
      triplet (scales ~1/64 m, ~1/32 m/s, ~1/512 rad), ~20 Hz.
- [ ] Confirm whether that stream has a per-point **validity/status** flag.

This is the one empirical capture that determines whether fully-autonomous overtake is
possible — and it's the exact piece `pd0wm` (PR #24221) never finished on the EV6.

## If something misbehaves

| Symptom | Likely cause | Next step |
|---|---|---|
| "Check cabling" / CAN timeout | Undecoded CAN signal (known community issue, ~6 users reported on 2026 Carnivals) | Capture the failing route; the rlog will show which message |
| ICBM does nothing | Stock ACC not latching 0x1AA | Grab a route with ICBM on; revert just the ICBM commit (`44337abd3`) if needed |
| Cluster UI blank / partial | `FR_CMR_03_50ms` not present on Carnival camera | Falls back gracefully — confirm via the `msg_1b5` presence in the rlog |
| Steering feels off | Torque tuning needs per-car adjustment | Note it; the tune points live in `torque_data/override.toml` + steer-delta in `values.py` |

## How to share results back

- **Route ID:** post the public route ID in the sunnypilot forum threads ("ccNC Port",
  "Support for newer vehicles with Angle Steering (LFA2)") and/or to `acidofrain` and
  `iwilliamlee` — both are actively looking for exactly this Hybrid data.
- **To me / this fork:** drop the route ID here and I can decode the longitudinal-relevant
  CAN traffic (ADRV SCC keep-alive bytes, `0x1FA`, `0x1AA` latching) to finish the
  camera-SCC longitudinal path.
