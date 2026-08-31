"""DEVELOPER-ONLY standalone test (NOT FOR CI): stubs cereal/openpilot in sys.modules,
so it must never be collected by the repo test suite. Run manually:
  python3 dev_test_auto_passing.py

Functional test for AutoPassingController.update() state machine.

Runs every gate/scenario with a controllable fake clock and synthetic model data.
Run from the repo root:  python3 test_auto_passing.py
"""
import sys
import types

import numpy as np

# --- stub dependencies BEFORE importing the module under test ---
fake_log = types.ModuleType('log')
fake_log.LaneChangeDirection = types.SimpleNamespace(none=0, left=1, right=2)
fake_log.LaneChangeState = types.SimpleNamespace(off=0, preLaneChange=1, laneChangeStarting=2)
fake_log.Desire = types.SimpleNamespace(laneChangeLeft=3, laneChangeRight=4)
sys.modules['cereal'] = types.SimpleNamespace(log=fake_log)

op = types.ModuleType('openpilot')
opc = types.ModuleType('openpilot.common')
sys.modules['openpilot'] = op
sys.modules['openpilot.common'] = opc
sys.modules['openpilot.common.constants'] = types.SimpleNamespace(CV=types.SimpleNamespace(MPH_TO_MS=0.44704))
sys.modules['openpilot.common.params'] = types.SimpleNamespace(
  Params=lambda: types.SimpleNamespace(get_bool=lambda k: True),
)

sys.path.insert(0, 'sunnypilot/selfdrive/controls/lib')
import auto_passing
from auto_passing import AutoPassingController

# --- fake clock (reset per scenario) ---
NOW = [0.0]
_real_monotonic = auto_passing.time.monotonic
auto_passing.time.monotonic = lambda: NOW[0]

NONE, LEFT, RIGHT = 0, 1, 2
LANE_CHANGE_SPEED_MIN = 20 * 0.44704  # 8.9408 m/s

# --- synthetic geometry ---
X = np.linspace(0, 50, 33)
STRAIGHT_Y = np.zeros(33)
PAR_Y = np.full(33, 3.5)                      # parallel adjacent lane 3.5 m away
DIVERGING_Y = 3.5 + np.linspace(0, 4, 33)     # turn lane drifting 4 m over 50 m
CURVE_Y = 60 - np.sqrt(np.maximum(60**2 - X**2, 0))   # 60 m radius


def mk(**overrides):
  """Default multi-lane straight-road scenario with a slow lead (25 < 30*0.85)."""
  base = dict(
    v_ego=25.0,
    cruise_speed=30.0,
    lead_prob=0.9,
    lane_line_probs=[0.7, 0.9, 0.9, 0.7],   # lanes on BOTH sides (3-lane)
    road_edge_stds=[0.9, 0.9],              # no confident road edges
    is_rhd=False,
    lateral_active=True,
    left_blinker=False,
    right_blinker=False,
    lane_change_state=0,                    # off
    left_blindspot=False,
    right_blindspot=False,
    path_x=list(X),
    path_y=list(STRAIGHT_Y),
    lane_change_left_prob=0.5,
    lane_change_right_prob=0.5,
    left_adj_x=list(X),
    left_adj_y=list(PAR_Y),
    right_adj_x=list(X),
    right_adj_y=list(PAR_Y),
  )
  base.update(overrides)
  c = AutoPassingController()
  c.enabled = True
  return c, base


def reset_clock():
  NOW[0] = 0.0


def step(c, s):
  return c.update(**s)


def advance(seconds):
  NOW[0] += seconds


def arm(c, s, seconds=3.05):
  """Step at t=0 (starts the sustain timer), wait past the sustain, then step."""
  reset_clock()
  step(c, s)
  advance(seconds)
  return step(c, s)


fails = []


def check(name, cond):
  if cond:
    print(f'  PASS  {name}')
  else:
    print(f'  FAIL  {name}')
    fails.append(name)


print('=== 1. normal arm (3-lane LHD -> passing side LEFT) ===')
c, s = mk()
reset_clock()
check('no suggestion at t=0', step(c, s) == NONE)
advance(2.9)
check('no suggestion before 3s sustain', step(c, s) == NONE)
advance(0.2)
check('suggests LEFT after 3s', step(c, s) == LEFT)

print('=== 2. RHD -> passing side RIGHT ===')
c, s = mk(is_rhd=True)
check('RHD suggests RIGHT', arm(c, s) == RIGHT)

print('=== 3. blinker hard gate clears + full 3s re-arm ===')
c, s = mk()
check('armed LEFT', arm(c, s) == LEFT)
s['left_blinker'] = True
check('blinker ON -> instant clear', step(c, s) == NONE)
s['left_blinker'] = False
step(c, s)          # timer restarts on THIS frame
advance(2.9)
check('needs 3s to re-arm after clear', step(c, s) == NONE)
advance(0.2)
check('re-armed after sustain', step(c, s) == LEFT)

print('=== 4. lane-change-in-progress hard gate ===')
c, s = mk(lane_change_state=1)   # preLaneChange
check('maneuver in progress -> none', arm(c, s) == NONE)

print('=== 5. speed floor / invalid cruise / lateral inactive ===')
c, s = mk(v_ego=LANE_CHANGE_SPEED_MIN - 0.5)
check('below speed floor -> none', arm(c, s) == NONE)
c, s = mk(cruise_speed=0.0)
check('invalid cruise -> none', arm(c, s) == NONE)
c, s = mk(lateral_active=False)
check('lateral inactive -> none', arm(c, s) == NONE)

print('=== 6. curve gate ===')
c, s = mk(path_y=list(CURVE_Y))
check('60m curve -> none', arm(c, s) == NONE)
c, s = mk()
check('straight -> LEFT', arm(c, s) == LEFT)

print('=== 7. blind-spot veto with instant re-arm ===')
c, s = mk()
check('armed LEFT', arm(c, s) == LEFT)
s['left_blindspot'] = True
check('left blindspot -> suppress', step(c, s) == NONE)
s['left_blindspot'] = False
check('blindspot clears -> instant re-arm (no new sustain)', step(c, s) == LEFT)

print('=== 8. model-desire gate ===')
c, s = mk(lane_change_left_prob=0.05)
check('model rejects left -> none', arm(c, s) == NONE)
s['lane_change_left_prob'] = 0.6
check('model endorses -> LEFT (instant)', step(c, s) == LEFT)

print('=== 9. turn-lane divergence gate ===')
c, s = mk(left_adj_y=list(DIVERGING_Y))
check('diverging left lane -> none', arm(c, s) == NONE)
s['left_adj_y'] = list(PAR_Y)
check('parallel lane -> LEFT (instant)', step(c, s) == LEFT)

print('=== 10. single-lane road never suggests ===')
c, s = mk(lane_line_probs=[0.1, 0.9, 0.9, 0.1],
          road_edge_stds=[0.1, 0.1])
check('single lane -> none', arm(c, s) == NONE)

print('=== 11. insufficient lane data ===')
c, s = mk(lane_line_probs=[0.5, 0.9])
check('short laneLineProbs -> none', arm(c, s) == NONE)

print('=== 12. 2-lane road-edge direction (user original rule) ===')
c, s = mk(lane_line_probs=[0.1, 0.9, 0.9, 0.7], road_edge_stds=[0.1, 0.9],
          lane_change_right_prob=0.5)
check('left edge -> suggest RIGHT', arm(c, s) == RIGHT)
c, s = mk(lane_line_probs=[0.7, 0.9, 0.9, 0.1], road_edge_stds=[0.9, 0.1],
          lane_change_left_prob=0.5)
check('right edge -> suggest LEFT', arm(c, s) == LEFT)

print('=== 13. lead-loss hold (anti-flap) ===')
c, s = mk()
check('armed LEFT', arm(c, s) == LEFT)      # NOW == 3.05
s['lead_prob'] = 0.0
step(c, s)                                  # first lead-loss frame: cleared_at = NOW
advance(1.0)
check('lead lost 1.0s -> still holding LEFT', step(c, s) == LEFT)
advance(0.6)                                # 1.6s since cleared_at
check('hold expired (1.6s) -> none', step(c, s) == NONE)
s['lead_prob'] = 0.9                        # lead returns
step(c, s)                                  # timer restarts on this frame
advance(2.9)
check('lead back, 2.9s -> none (re-sustain)', step(c, s) == NONE)
advance(0.2)
check('lead back, 3.1s -> LEFT', step(c, s) == LEFT)

print('=== 14. slow-lead speed margin ===')
c, s = mk(v_ego=26.0)   # 26 > 30*0.85 = 25.5 -> NOT a slow lead
check('above margin -> none', arm(c, s) == NONE)
c, s = mk(v_ego=25.0)
check('below margin -> LEFT', arm(c, s) == LEFT)

print('=== 15. empty path data (conservative) ===')
c, s = mk(path_x=[], path_y=[], left_adj_x=[], left_adj_y=[],
          right_adj_x=[], right_adj_y=[])
check('no path data -> none', arm(c, s) == NONE)

print('=== 16. turn-lane scenario from the user (left lane + turn lane opens) ===')
# 2-lane: left edge present (median), lane on RIGHT exists; left turn lane opening
# shows a left-adjacent lane line that DIVERGES and the model does not endorse it.
c, s = mk(lane_line_probs=[0.7, 0.9, 0.9, 0.7],  # turn lane line visible on left
          road_edge_stds=[0.9, 0.1],             # right edge (2-lane, rightmost)
          lane_change_left_prob=0.05,            # model rejects the turn lane
          left_adj_y=list(DIVERGING_Y))          # turn lane diverges
check('turn lane not suggested (desire+divergence)', arm(c, s) == NONE)

# restore clock
auto_passing.time.monotonic = _real_monotonic

print()
if fails:
  print(f'{len(fails)} FAILURES: {fails}')
  sys.exit(1)
print('ALL SCENARIOS PASSED')
