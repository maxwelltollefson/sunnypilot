# HKG-Sibling Research Findings (angle steering, longitudinal, flag landmines)

Consolidated findings from a systematic scan of the HKG/CCNC fork landscape. These
directly inform future work on the Carnival HEV.

## 1. The Carnival's steering message already carries BOTH torque AND angle fields

The Carnival's `LKAS_ALT` (0x110 / `BO_ 272`) message contains, side by side:

| Signal | Bits | Meaning | Used by this fork? |
|---|---|---|---|
| `StrTqReqVal` | `41|11` | Torque request (offset -1024) | ✅ torque path (current) |
| `ADAS_StrAnglReqVal` | `82|14` | Steering **angle** request, capped 176.7° | ❌ unused |
| `ADAS_ACIAnglTqRedcGainVal` | `96|8` | Torque-reduction gain (0..1) | ❌ unused |
| `LKAS_ANGLE_ACTIVE` | `77|2` | Angle-command active state | ❌ unused |

**Conclusion:** the Carnival's physical steering interface can carry a *native angle
command* (`ADAS_StrAnglReqVal`) in the *same* message we already send. Angle steering is
not a new message — it is a **field-swap** (populate the angle field instead of the torque
field). This is what `hkg-angle-steering-2025` does internally (`LKAS_ANGLE_CMD`).

## 2. The closest sibling (Santa Fe HEV HDA2, CCNC) is angle-steering

`HYUNDAI_SANTA_FE_HEV_5TH_GEN` ("Hyundai Santa Fe Hybrid (with HDA II) 2024-25") is
configured:

```
CarSpecs(mass=2258, wheelbase=2.95, steerRatio=14.14)
flags=HyundaiFlags.HYBRID | HyundaiFlags.CANFD_ANGLE_STEERING
```

This is a **near-twin** of the Carnival HEV (mass 2253 vs 2258, steerRatio 14.23 vs
14.14, both CCNC-HDA2-HEV). sunnypilot ships it as **angle-steering**.

**Implication:** the Carnival HEV is very likely *capable* of `CANFD_ANGLE_STEERING` too —
it is simply not yet *added* to the angle set (no Carnival HEV entry exists in the angle
branches). This reopens the "angle would be better if tuned" question with real evidence:
the angle path reuses the Carnival's existing `LKAS_ALT` message, so it is a field-swap,
not a new subsystem.

Angle-steering mechanism (from `hkg-angle-steering-2025` `interface.py`):

```python
if ret.flags & HyundaiFlags.CANFD_ANGLE_STEERING:
    ret.steerControlType = structs.CarParams.SteerControlType.angle
```

and in `hyundaicanfd.py`, the LKAS message populates `LKAS_ANGLE_CMD` (angle) instead of a
torque value, with ADAS-ECU forwarding (same ADAS-ECU path the Carnival uses):

> "For cars with an ADAS ECU (commonly HDA2), by sending LKAS actuation messages we're
> telling the ADAS ECU to forward our steering and disable stock LFA lane centering."

## 3. Flag-collision landmine: `CCNC` and `CANFD_ANGLE_STEERING` share bits

Both the ccnc-port lineage (our base) and the angle-steering lineage independently
grabbed the same flag bits, on divergent bases:

| | `HyundaiFlags` | `HyundaiSafetyFlags` |
|---|---|---|
| **CCNC** (ours, ccdunder) | `2 ** 27` | `1024` |
| **CANFD_ANGLE_STEERING** (hkg-angle branch) | `2 ** 27` | `1024` |

**Consequence:** a naive "fold in angle steering" would silently corrupt the `CCNC` flag
(or vice-versa), producing the kind of hard-to-diagnose behavior flagged repeatedly this
session. To add angle steering alongside CCNC, one of them must be re-homed to a free bit
(this fork already uses `2**28` for `CANFD_RADAR`; free bits include `2**23`, `2**26`,
and anything ≥ `2**29`).

## 4. Longitudinal status across the CCNC family

- `santa-fe-ccnc-hda2` — Santa Fe CCNC HDA2 is `UNSUPPORTED_LONGITUDINAL` (same as this
  fork). No one in the CCNC family has working longitudinal.
- `ioniq-6-hda2-long` — is just a merge-with-master snapshot, NOT a distinct longitudinal
  implementation. Dead end.
- **`hkg-adas-ecu-drv-interceptor` (`devtekve`, PR #196) — a THIRD longitudinal path, most
  directly relevant to the Carnival.** It adds `ADAS_DRV_INTERCEPT`:
  - Detects a heartbeat message (`ADAS_INTERCEPTOR_HEARTBEAT_MSG`) in the fingerprint →
    sets `HyundaiFlagsSP.ADAS_ECU_INTERCEPTOR` + a dedicated safety param
    `ADAS_DRV_ECU_LONG_INTERCEPTOR`.
  - Sends `create_adas_drv_intercept_msg(...)` to the **ADAS ECU (0x730)** to take over
    longitudinal — targeting exactly the ADAS-ECU HDA2 architecture the Carnival has
    (Ecu.adas = 0x730 is already in our `values.py`).
  - Status (from DevTekVE Discord, 2026): *still alpha* — "We do not have long enabled yet
    on our cars so I won't get your hopes high." No CCNC/HDA2 car has working longitudinal
    via any of the three paths (camera-SCC, radar-SCC, ADAS-ECU-intercept) yet.

### Harness note (matters for the Carnival Q-harness)

From the DevTekVE discussion: the **ADAS ECU uses the Hyundai R connector; the camera uses
the Q connector.** The Carnival (Q harness, camera-SCC) plugs the comma into the *camera*,
not the ADAS ECU. So the ADAS-ECU-interceptor path would require either an R-harness
(direct ADAS-ECU plug) or the "silence the ADAS ECU via diagnostics mode" approach DevTekVE
mentions as the preferred route ("we should be able to silence the ADAS ECU putting it into
diagnostics mode similar to how we silence other car's SCC's").

## 5. Steering torque/limit reference (upstream default, for future angle/torque tuning)

Upstream `CarControllerParams` defaults for HKG: `STEER_MAX = 384` (most HKG),
`STEER_DELTA_UP = 2 / DOWN = 3` on CAN-FD, `STEER_DRIVER_ALLOWANCE = 250`,
`STEER_THRESHOLD = 250`. The Carnival HEV uses `STEER_MAX = 384` with `STEER_DELTA_UP = 6 /
DOWN = 4` (doubled, per ccdunder's observed ~10 Nm/s stock rate). This is the baseline
against which any angle-vs-torque A/B should be judged.

## References

- sunnypilot `hkg-angle-steering-2025-*` branch family (angle-steering implementation, PR #119, actively syncing)
- sunnypilot `santa-fe-ccnc-hda2` + its opendbc commit `d99f2170` (Santa Fe HEV HDA2 = CANFD_ANGLE_STEERING)
- sunnypilot `hkg-adas-ecu-drv-interceptor` / devtekve PR #196 (ADAS_DRV_INTERCEPT longitudinal)
- DevTekVE Discord discussion: ADAS ECU = R connector, camera = Q connector; silence-ADAS-ECU approach
- ccdunder `kia-carnival-25-sp-dev` (our base's CCNC flag lineage)
