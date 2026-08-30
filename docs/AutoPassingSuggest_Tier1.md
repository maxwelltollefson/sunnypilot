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
