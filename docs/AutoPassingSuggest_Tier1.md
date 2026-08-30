# Tier 1 — Auto-Passing Suggest (slow-lead lane-change suggestion)

## Goal

When driving with a lead vehicle ahead that has forced a meaningful speed drop (a
"slow car" on a multi-lane road), **suggest** a lane change to the passing side, and
let the driver execute it with the turn signal. This automates the *detection and
direction decision* — the human stays the final safety check on the one thing the
sensors can't yet confirm (a vehicle closing fast in the adjacent lane from behind).

## Why "suggest + blinker-confirm" and not full auto

- The HDA2 side radar (BCA/BCW) reports **presence + warning flags**, not
  free-space range or a rear-quarter closing velocity. "No one *beside* me" is not
  "no one *closing from behind*". The existing ALC already uses BCA/BCW strictly as a
  **veto**, never as a **go**.
- Dropping the driver's blinker confirm requires a rear-quadrant closing signal that
  is not yet decoded (Tier 2, gated on a route capture).

## Trigger (slow-lead detection)

All must hold for a short sustained window:

1. Feature param `AutoPassingSuggest` enabled.
2. Lateral active (MADS/openpilot steering engaged).
3. Multi-lane road: `modelV2.laneLineProbs` shows lane lines on **both** sides OR
   one side's lane line visible (see direction heuristic below). Single-lane roads
   (one lane line total) never suggest.
4. **Lead present** (`modelV2.leads[0]` prob > threshold) AND
   **`carState.vEgo < carState.cruiseState.speed * (1 - margin)`** — i.e. we've been
   pulled below the set speed by the lead — sustained for `SLOW_LEAD_TIME` seconds.
5. Above `LANE_CHANGE_SPEED_MIN` (already the ALC floor).

## Full edge-case matrix (hardened implementation)

The controller applies these gates in order — a hard gate drops any active
suggestion immediately; a soft gate simply prevents (re-)arming:

| # | Condition | Type | Behavior |
|---|---|---|---|
| 1 | Feature disabled / lateral inactive / cruise speed invalid | Hard | No suggestion, clear state |
| 2 | `vEgo < 20 mph` (lane-change speed floor) | Hard | No suggestion |
| 3 | Either blinker on (driver already acting) | Hard | No suggestion, clear |
| 4 | Lane change already in progress (`lane_change_state != off`) | Hard | No suggestion, clear |
| 5 | Sharp curve ahead: model-predicted path curvature > 0.01 /m (~100 m radius) over the next 50 m | Hard | No suggestion, clear |
| 6 | Lead lost briefly | Hold | Keep the armed suggestion for 1.5 s (anti-flap), frozen direction |
| 7 | Lead present + below set speed for < 3 s | Soft | Don't arm yet (entry sustain) |
| 8 | Insufficient lane-line data (`laneLineProbs` < 4 entries) | Soft | No suggestion |
| 9 | Single-lane road (no adjacent lane) | Soft | Never suggest into a nonexistent lane |
| 10 | Blind spot (BCA/BSM) on the target side | Soft | Drop suggestion instantly; re-arms immediately when clear (slow-lead timer keeps running) |
| 11 | Lane on both sides (3+ lanes) | — | Passing side by traffic convention (`is_rhd`) |

## Map data: evaluated and intentionally not used

The user asked about map data without comma prime. `mapd` + offline OSM downloads
**are** available without a subscription, but the `liveMapDataSP` schema in this fork
carries only **speed limits + road name** — no road curvature and no road class
(motorway/controlled-access). Those are the only fields that could meaningfully gate a
lane change, so wiring mapd in would add a service dependency for zero gating value.

The curve gate (#5) instead uses the **driving model's own predicted trajectory**
(`modelV2.position`), which is a better signal anyway (it reflects the actual sensed
road, not a stale map tile). If mapd later gains curvature/road-class fields, #5 can be
augmented; see `docs/HKG_sibling_research.md`.

## Surfacing (implemented)

The suggestion is published on the sunnypilot-owned `ModelDataV2SP.autoPassingSuggest`
(new `LaneChangeDirectionSP` enum: none/left/right) and surfaced as a soft,
low-priority alert (`EventNameSP.autoPassingSuggest`, "Passing opportunity / Signal to
change lanes", single low chime). The maneuver itself still executes only through the
existing blinker → ALC path; the alert is informational.

## Direction heuristic (roadEdges + lane count)

Given `roadEdges` (road-surface boundary) and `laneLineProbs` (left/right lane-line
existence), decide the *only* valid pass direction:

- **Road edge on the left** (no lane to the left) → suggest **right**.
- **Road edge on the right** (no lane to the right) → suggest **left**.
- **Neither edge adjacent** (lane on both sides → ≥3-lane road) → suggest the
  **passing side** from `traffic_convention` (left for RHD, right for LHD). This is
  conservative: on a 3-lane we suggest the passing lane, which is the conventional
  safe choice.
- **Both edges present** (single lane) → no suggestion.

`roadEdges`/`laneLineProbs` come from the driving model's `ModelDataV2` prediction
(the lane-line/edge curves the model already emits); no new sensing required.

## Gating (reuse existing ALC safety)

Before arming the suggestion, require the *existing* ALC preconditions to already be
satisfied (they are evaluated in `DesireHelper`/`AutoLaneChangeController`):

- `BCA_LEFT`/`BCA_RIGHT` (side radar) == HIDDEN on the target side.
- `BCW_LtIndSta`/`BCW_RtIndSta` == 0 on the target side.
- Not below `LANE_CHANGE_SPEED_MIN`.
- No driver brake press (the ALC timer already vetoes after brake).

When armed, pre-fill `lane_change_direction` so the suggestion UI shows an arrow, and
surface an on-screen "passing opportunity" glyph. The maneuver itself still fires
through the normal blinker → `preLaneChange` → `laneChangeStarting` state machine, so
**all existing safety (blind-spot veto, road-edge block, driver-attention DM) applies
unchanged.**

## Files touched

- `selfdrive/modeld/modeld.py` — pass `model_v2` (for lanes/edges/leads) +
  `traffic_convention` into `DH.update(...)`.
- `selfdrive/controls/lib/desire_helper.py` — new `suggest_lane_change` state +
  trigger/direction logic; extend `update()` signature.
- `sunnypilot/selfdrive/controls/lib/auto_lane_change.py` — expose the suggestion
  direction (read-only) plus the existing vetoes.
- `selfdrive/ui/...` — a `AutoPassingSuggest` toggle (default OFF) + on-road glyph.
- `common/params_keys.h` / sunnypilot params — register `AutoPassingSuggest`.

## Safety constraints honored

- Default OFF.
- Never *executes* a lane change on its own — only pre-arms direction so the driver
  can confirm with the blinker.
- Direction is road-edge-constrained (cannot suggest into a road edge).
- Blind-spot / BCA / road-edge vetoes are unchanged.
- Feature does not touch longitudinal; stock SCC continues to control speed.

## Prior art: the HDA2 side radar has been decoded before (Tier 2 lead)

The "rear-quadrant closing-vehicle" signal Tier 2 needs has **partially been decoded
on sibling HDA2 platforms**. This is the concrete starting point for the route decode.

### Mando corner-radar point cloud (EV6 / Ioniq 6 / Ioniq 5)

- **Decoder source**: `opendbc/dbc/generator/hyundai/hyundai_kia_mando_corner_radar.py`
  (already present in this fork's opendbc).
- **Messages**: metadata `0x100`/`0x200`, radar **points** `0x101`/`0x201` at 20 Hz
  (up to 65 points, 5 per message), checksum `0x104`/`0x204`.
- **Per-point signals** (what we want for "is a car closing from behind"):
  - `POINT_n_DISTANCE` (scale 1/64 m)
  - `POINT_n_REL_VELOCITY` (scale 1/32 m/s, offset -66)  ← the closing-speed signal
  - `POINT_n_AZIMUTH` (scale 1/512 rad)
- **Author / status**: `pd0wm` (Willem Melching), comma.ai/openpilot PR #24221
  ("EV6 corner radar", 2022). **Closed, never merged.** Left unfinished TODOs:
  *"Find status flags, Find relative speed"* — the point cloud decoded but validity
  flags incomplete. No production fork ships this parser.

### ECU plumbing already in-tree

- `Ecu.cornerRadar = 0x7b7` is already defined in `hyundai/values.py` `extra_ecus`
  (so the corner-radar ECU is queried during fingerprinting on HKG).

### Community BSM (presence-only) work

- `whoisdomi` (FrogPilot Discord) got **blind-spot presence** working for the Ioniq 6 —
  this is the `leftBlindspot`/`rightBlindspot` booleans, *not* the range/velocity
  point cloud. Referenced in the sunnypilot "ESCC for CAN FD" forum thread.

### Carnival (CCNC) caveat

The Carnival HDA2 is a CCNC/CAN-FD car. `acidofrain`'s reverse-engineering shows its
blind-spot data surfaces as **presence flags** via `ADAS_CMD_50_50ms`
(`BCW_LtIndSta`/`BCW_RtIndSta`) — which is what this fork already reads. It is **not
yet confirmed** whether the Carnival also transmits a Mando-style rear-lateral *point
stream* (range + relative velocity) on `0x100/0x101` (or a CCNC-specific equivalent).

### Tier 2 decode target (what to grep for in the route)

When a full rlog is available, resolve these against the Carnival's actual traffic:

1. Is there traffic on `0x100`/`0x200`/`0x101`/`0x201` (Mando corner-radar format)?
2. If not, find the CCNC rear-lateral source: look for a message carrying a repeating
   `DISTANCE`-like (~1/64 m) + `REL_VELOCITY`-like (~1/32 m/s) + `AZIMUTH`-like signal
   triplet, likely 20 Hz, from the `0x7b7` corner-radar ECU.
3. Confirm a per-point **validity/status** flag (the piece `pd0wm` never finished) so
   tracks can be trusted for a "car closing in adjacent lane" gate.

Once a source with range + relative velocity + validity is decoded, the
`AutoPassingController` can drop the "suggest" downgrade and gate an autonomous pass on
"no object closing from behind at > X m/s relative in the target lane".
