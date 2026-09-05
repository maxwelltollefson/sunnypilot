"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Tier 1 "Auto-Passing Suggest": detect a slow lead vehicle on a multi-lane road and
pre-suggest a lane change toward the passing side. The maneuver still requires the
driver's blinker to execute; this module only computes *when* to suggest and *which*
direction via the driving model's road-edge + lane-line predictions.

Edge-case handling (see docs/AutoPassingSuggest_Tier1.md):
- Hard gates drop any active suggestion immediately: feature off, lateral inactive,
  invalid cruise speed, below lane-change speed floor, any blinker on, an active
  lane-change maneuver, or sharp path curvature ahead (from the model's own
  predicted trajectory — no map data needed; mapd/OSM's liveMapDataSP schema carries
  only speed limits + road names, not curvature or road class).
- Slow-lead detection uses a 3s entry sustain + a 1.5s exit hold (anti-flap), and
  freezes the suggestion during the hold so it cannot flip direction mid-hold.
- Direction heuristic: road edge on a side forbids that direction; both sides open
  -> passing side by traffic convention; no adjacent lane -> no suggestion.
- Blind-spot veto: the target side must be free (BCA/BSM); a blind-spot appearance
  drops the suggestion immediately, and it re-arms instantly once clear (the slow-lead
  timer keeps running through suppression).
"""
import time

import numpy as np
from cereal import log
from openpilot.common.constants import CV
from openpilot.common.params import Params, UnknownKeyName

LaneChangeDirection = log.LaneChangeDirection
LaneChangeState = log.LaneChangeState

# Sentinel for "_direction_from_road": adjacent lane exists on BOTH sides (>=3 lanes),
# so the caller picks the passing side via traffic convention. Distinct from `none`,
# which means NO adjacent lane (or insufficient data) -> no suggestion.
BOTH_LANES = -1

# Tunables (conservative, unvalidated defaults; see docs/AutoPassingSuggest_Tier1.md)
SLOW_LEAD_SPEED_MARGIN = 0.15      # vEgo below cruiseState.speed * (1 - margin)
SLOW_LEAD_MIN_TIME = 3.0           # seconds of sustained slow-lead before suggesting
SLOW_LEAD_HOLD_TIME = 1.5          # seconds to hold an armed suggestion after lead clears
LEAD_PROB_THRESHOLD = 0.5
LANE_LINE_PROB_THRESHOLD = 0.5
LANE_CHANGE_SPEED_MIN = 20 * CV.MPH_TO_MS
MAX_PATH_CURVATURE = 0.01          # 1/m (~100 m radius) — suppress in curves
PATH_LOOKAHEAD_X = 50.0            # meters of predicted path to check for curvature
LANE_CHANGE_DESIRE_THRESHOLD = 0.2 # model's lane-change desire prob for the target side
MAX_ADJ_LANE_DIVERGENCE = 2.0      # meters of lateral divergence over the lookahead
DIVERGENCE_LOOKAHEAD_X = 40.0      # meters ahead to compare adjacent lane vs ego path


class AutoPassingController:
  def __init__(self):
    self.params = Params()
    self.enabled = False
    self.slow_lead_start = None
    self.slow_lead_cleared_at = None
    self.suggest_direction = LaneChangeDirection.none
    self._param_read_counter = 0

  def read_params(self) -> None:
    if self._param_read_counter % 50 == 0:
      try:
        self.enabled = self.params.get_bool("AutoPassingSuggest")
      except UnknownKeyName:
        # The param registry (params_pyx) is a compiled prebuilt. If it predates
        # the AutoPassingSuggest key (18b2ca5a1), the key is absent and get_bool
        # raises. Never let a missing experimental-flag param crash modeld; the
        # feature simply stays disabled until the prebuilt is regenerated.
        self.enabled = False
    self._param_read_counter += 1

  def _clear(self) -> None:
    self.suggest_direction = LaneChangeDirection.none
    self.slow_lead_start = None
    self.slow_lead_cleared_at = None

  @staticmethod
  def _direction_from_road(lane_line_probs, road_edge_stds) -> int:
    """Decide the only valid passing direction from lane-line + road-edge predictions.

    lane_line_probs: [left_adj, left, right, right_adj] (floats 0..1)
    road_edge_stds : [left_edge_std, right_edge_std] — low std means a road edge is
                     confidently detected on that side (no lane beyond it).

    Returns LaneChangeDirection.left/right, BOTH_LANES (lane on both sides),
    or LaneChangeDirection.none (no adjacent lane / insufficient data).
    """
    if len(lane_line_probs) < 4:
      return LaneChangeDirection.none

    left_adj_lane = lane_line_probs[0] > LANE_LINE_PROB_THRESHOLD
    right_adj_lane = lane_line_probs[3] > LANE_LINE_PROB_THRESHOLD

    # A road edge on a side means the paved surface ends there -> no lane beyond.
    has_left_edge = len(road_edge_stds) >= 2 and road_edge_stds[0] < 0.5
    has_right_edge = len(road_edge_stds) >= 2 and road_edge_stds[1] < 0.5

    lane_on_left = left_adj_lane and not has_left_edge
    lane_on_right = right_adj_lane and not has_right_edge

    if lane_on_left and lane_on_right:
      # Lane on both sides (>=3 lanes) — handled by caller using traffic convention.
      return BOTH_LANES
    if lane_on_left:
      return LaneChangeDirection.left
    if lane_on_right:
      return LaneChangeDirection.right
    return LaneChangeDirection.none

  @staticmethod
  def _max_path_curvature(path_x, path_y) -> float:
    """Max |curvature| of the model's predicted ego path over the lookahead horizon.

    Uses the driving model's own position prediction (no map dependency). Returns
    inf when data is insufficient, which conservatively suppresses the suggestion.
    """
    if len(path_x) < 4 or len(path_y) < 4:
      return float('inf')

    xs = np.asarray(path_x, dtype=float)
    ys = np.asarray(path_y, dtype=float)
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]

    idx = np.where(xs <= PATH_LOOKAHEAD_X)[0]
    if len(idx) < 4:
      return float('inf')
    xs, ys = xs[idx], ys[idx]

    # The model's predicted path is already smooth; no additional filtering (edge
    # padding in a smoothing kernel distorts the far samples and spikes curvature).
    dy = np.gradient(ys, xs)
    ddy = np.gradient(dy, xs)
    with np.errstate(divide='ignore', invalid='ignore'):
      curv = np.abs(ddy) / np.power(1.0 + dy ** 2, 1.5)
    curv = curv[np.isfinite(curv)]
    return float(curv.max()) if len(curv) else float('inf')

  @staticmethod
  def _lane_divergence(ego_x, ego_y, adj_x, adj_y) -> float:
    """Lateral drift of an adjacent lane line relative to the ego path over the lookahead.

    A turn lane, exit ramp, or merge lane diverges from the ego path; a parallel travel
    lane does not. Returns inf when data is insufficient (conservatively suppresses).
    """
    if len(ego_x) < 4 or len(ego_y) < 4 or len(adj_x) < 4 or len(adj_y) < 4:
      return float('inf')

    ex = np.asarray(ego_x, dtype=float)
    ey = np.asarray(ego_y, dtype=float)
    ax = np.asarray(adj_x, dtype=float)
    ay = np.asarray(adj_y, dtype=float)

    # interp requires sorted x; model outputs should be monotonic but be safe
    ex_order = np.argsort(ex)
    ex, ey = ex[ex_order], ey[ex_order]
    ax_order = np.argsort(ax)
    ax, ay = ax[ax_order], ay[ax_order]

    def y_at(xq, xs, ys):
      if xs.size == 0 or xs[0] > xq or xs[-1] < xq:
        return None
      return float(np.interp(xq, xs, ys))

    e0, e40 = y_at(0.0, ex, ey), y_at(DIVERGENCE_LOOKAHEAD_X, ex, ey)
    a0, a40 = y_at(0.0, ax, ay), y_at(DIVERGENCE_LOOKAHEAD_X, ax, ay)
    if None in (e0, e40, a0, a40):
      return float('inf')

    # divergence = how much the adjacent lane's lateral motion differs from ours
    return abs((a40 - a0) - (e40 - e0))

  def update(self, v_ego, cruise_speed, lead_prob, lane_line_probs, road_edge_stds,
             is_rhd, lateral_active, left_blinker, right_blinker, lane_change_state,
             left_blindspot, right_blindspot, path_x, path_y,
             lane_change_left_prob, lane_change_right_prob,
             left_adj_x, left_adj_y, right_adj_x, right_adj_y) -> int:
    """Returns a suggested LaneChangeDirection, or none.

    All inputs are read-only; the only side effect is internal suggestion state.
    """
    # Hard gates: drop any active suggestion immediately.
    if (not self.enabled or not lateral_active or cruise_speed <= 0 or
        v_ego < LANE_CHANGE_SPEED_MIN or
        left_blinker or right_blinker or
        lane_change_state != LaneChangeState.off):
      self._clear()
      return LaneChangeDirection.none

    # Curve gate: never suggest into/through a sharp curve (model-predicted path).
    if self._max_path_curvature(path_x, path_y) > MAX_PATH_CURVATURE:
      self._clear()
      return LaneChangeDirection.none

    # Slow-lead detection with entry sustain + exit hold (anti-flap hysteresis).
    slow_lead = lead_prob >= LEAD_PROB_THRESHOLD and v_ego < cruise_speed * (1 - SLOW_LEAD_SPEED_MARGIN)

    if slow_lead:
      self.slow_lead_cleared_at = None
      if self.slow_lead_start is None:
        self.slow_lead_start = time.monotonic()
    else:
      self.slow_lead_start = None
      if self.slow_lead_cleared_at is None:
        self.slow_lead_cleared_at = time.monotonic()
      if time.monotonic() - self.slow_lead_cleared_at > SLOW_LEAD_HOLD_TIME:
        self._clear()
        return LaneChangeDirection.none
      # Inside the hold window: freeze the armed suggestion (may be none).
      return self.suggest_direction

    # Entry sustain: require SLOW_LEAD_MIN_TIME before the first suggestion.
    if time.monotonic() - self.slow_lead_start < SLOW_LEAD_MIN_TIME:
      return self.suggest_direction

    # Direction heuristic.
    d = self._direction_from_road(lane_line_probs, road_edge_stds)
    if d == BOTH_LANES:
      # Lane on both sides (>=3 lanes): use the passing side (left for LHD, right for RHD).
      d = LaneChangeDirection.right if is_rhd else LaneChangeDirection.left
    elif d == LaneChangeDirection.none:
      # No adjacent lane (single-lane road / both edges present) or insufficient data:
      # never suggest a lane change into a lane that doesn't exist.
      self.suggest_direction = LaneChangeDirection.none
      return LaneChangeDirection.none

    # Blind-spot veto on the target side: suppress while occupied; re-arms when clear.
    if ((d == LaneChangeDirection.left and left_blindspot) or
        (d == LaneChangeDirection.right and right_blindspot)):
      self.suggest_direction = LaneChangeDirection.none
      return LaneChangeDirection.none

    # Model-desire gate: the driving model is trained on human lane-change behavior and
    # keeps its desire probability low when a change into that lane is inappropriate
    # (turn lanes, exit lanes, no-passing zones). Require it to endorse the direction.
    desire_prob = lane_change_left_prob if d == LaneChangeDirection.left else lane_change_right_prob
    if desire_prob < LANE_CHANGE_DESIRE_THRESHOLD:
      self.suggest_direction = LaneChangeDirection.none
      return LaneChangeDirection.none

    # Divergence gate: a turn lane / exit ramp / merge lane diverges from our path; a
    # parallel travel lane does not. Suppress when the target lane drifts away from us.
    if d == LaneChangeDirection.left:
      divergence = self._lane_divergence(path_x, path_y, left_adj_x, left_adj_y)
    else:
      divergence = self._lane_divergence(path_x, path_y, right_adj_x, right_adj_y)
    if divergence > MAX_ADJ_LANE_DIVERGENCE:
      self.suggest_direction = LaneChangeDirection.none
      return LaneChangeDirection.none

    self.suggest_direction = d
    return d
