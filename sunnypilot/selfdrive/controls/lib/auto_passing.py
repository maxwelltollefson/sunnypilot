"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Tier 1 "Auto-Passing Suggest": detect a slow lead vehicle on a multi-lane road and
pre-suggest a lane change toward the passing side. The maneuver still requires the
driver's blinker to execute; this module only computes *when* to suggest and *which*
direction via the driving model's road-edge + lane-line predictions.
"""
import time

from cereal import log
from openpilot.common.params import Params

LaneChangeDirection = log.LaneChangeDirection

# Slow-lead parameters (unvalidated defaults; conservative)
SLOW_LEAD_SPEED_MARGIN = 0.15      # vEgo below cruiseState.speed * (1 - margin)
SLOW_LEAD_MIN_TIME = 3.0           # seconds of sustained slow-lead before suggesting
LEAD_PROB_THRESHOLD = 0.5
LANE_LINE_PROB_THRESHOLD = 0.5


class AutoPassingController:
  def __init__(self):
    self.params = Params()
    self.enabled = False
    self.slow_lead_start = None
    self.suggest_direction = LaneChangeDirection.none
    self._param_read_counter = 0

  def read_params(self) -> None:
    if self._param_read_counter % 50 == 0:
      self.enabled = self.params.get_bool("AutoPassingSuggest")
    self._param_read_counter += 1

  @staticmethod
  def _direction_from_road(lane_line_probs, road_edge_stds) -> int:
    """Decide the only valid passing direction from lane-line + road-edge predictions.

    lane_line_probs: [left_adj, left, right, right_adj] (floats 0..1)
    road_edge_stds : [left_edge_std, right_edge_std] — low std means a road edge is
                     confidently detected on that side (no lane beyond it).

    Returns LaneChangeDirection.left/right/none.
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
      return LaneChangeDirection.none
    if lane_on_left:
      return LaneChangeDirection.left
    if lane_on_right:
      return LaneChangeDirection.right
    return LaneChangeDirection.none

  def update(self, v_ego, cruise_speed, lead_prob, lane_line_probs, road_edge_stds,
             is_rhd: bool, lateral_active: bool) -> int:
    """Returns a suggested LaneChangeDirection, or none.

    All inputs are read-only; no side effects beyond internal state.
    """
    if not self.enabled or not lateral_active or cruise_speed <= 0:
      self.suggest_direction = LaneChangeDirection.none
      return LaneChangeDirection.none

    # 1. Slow-lead detection: lead present and we've been pulled below set speed.
    slow_lead = lead_prob >= LEAD_PROB_THRESHOLD and v_ego < cruise_speed * (1 - SLOW_LEAD_SPEED_MARGIN)

    if slow_lead and self.slow_lead_start is None:
      self.slow_lead_start = time.monotonic()
    elif not slow_lead:
      self.slow_lead_start = None

    sustained = self.slow_lead_start is not None and (time.monotonic() - self.slow_lead_start) >= SLOW_LEAD_MIN_TIME
    if not sustained:
      self.suggest_direction = LaneChangeDirection.none
      return LaneChangeDirection.none

    # 2. Direction heuristic.
    d = self._direction_from_road(lane_line_probs, road_edge_stds)
    if d == LaneChangeDirection.none:
      # Lane on both sides: use the passing side (left for LHD countries, right for RHD).
      d = LaneChangeDirection.right if is_rhd else LaneChangeDirection.left

    self.suggest_direction = d
    return d
