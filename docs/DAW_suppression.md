# DAW (Driver Attention Warning) — "Take a Break" suppression investigation

## The problem

The 2025 Carnival HEV's **car-side DAW** (Driver Attention Warning / Attention Assist)
pops a "Consider Taking a Break" message on the **instrument cluster** when it sees no
driver steering input for a while. This is *the car's own system*, not openpilot's
driver-monitoring alert (those are two different things).

When openpilot (or stock HDA2) is steering, the driver naturally provides little wheel
input, so the car's DAW misfires as "driver drowsy". On newer HKG cars (2023+), the
DAW "take a break" warning **cannot be disabled** from the cluster/head-unit settings —
the user-visible toggle only covers the leading-vehicle-departure alert, not the break
recommendation (confirmed by multiple owners and the 2025 Sorento/Carnival owner's
manuals).

## The signal (confirmed in DBC)

Message `BO_ 282` ("Sent by the camera containing DAW information"):

| Signal | Meaning |
|---|---|
| `DAW_SysSta` | Attention level: 5=highest/best … 1=decreasing, 0=System Off, 14=Standby, 15=Fail |
| `DAW_WrnMsgSta` | Popup control: 0=no warning, **1=Rest Recommend ("take a break")**, 2=Hands-Off TMS |
| `DAW_TimeRstReq` | Requests CLU "Last Break Time" reset |
| `CF_LkasDawStatus` | (classic CAN) LKA DAW state, CLU |

## Prior art — the Palisade/Telluride community solution

sunnypilot forum thread **"2023 - 2025 Hyundai Palisade / Kia Telluride"** (id #444)
documents a working approach used on the sibling CAN-FD HKG platform:

> `# DAW (Driver Attention Warning) suppression for CAN_CANFD_BLENDED`
> `# openpilot fully replaces camera via LKAS11, so we must always send ALERTS_364`
> `# Otherwise ECU thinks camera is dead and disables DAW settings + adaptive lights + LKAS`
> `# Force DAW_Warning=0 to suppress "Consider Taking a Break" alerts`

Key facts from the same thread:

- Technique = **force `DAW_Warning = 0`** in the camera-replacement message openpilot
  re-sends (the `ALERTS_364` message on CAN-FD-BLENDED cars).
- **Caveat (important):** re-sending the message creates a **conflict with the camera's
  native message**. The ECU may react by **disabling DAW settings + adaptive high-beam +
  LKAS** as a "duplicate message / safety" response. So this is *not* a free win — it
  must be done carefully and validated that it doesn't knock out other features.
- `DAW_SysSta` values clarified by `@Liwei_Chou`: it's an attention *level*, not a
  countdown.

## Status on the Carnival

- The suppression code is **not merged** into sunnypilot's public `opendbc` or `sunnypilot`
  branches — it exists as a community user's fork (`pal23sp-hda2`-style branch) plus the
  signal knowledge above.
- The Carnival is a **CCNC/CAN-FD** car, NOT `CAN_CANFD_BLENDED`. Its DAW message path
  and camera-replacement behavior **differ** from the Palisade/Telluride, so the exact
  `ALERTS_364` pattern may not transfer directly. It needs the Carnival's own DAW traffic
  to reverse which message to suppress and confirm no high-beam/LKAS side effects.

## Path forward (gated on route data)

1. Capture a preserved rlog with the DAW actively firing (drive until the "take a break"
   popup appears, ideally hands-off while openpilot steers).
2. In cabana, identify the Carnival's DAW message + confirm the `DAW_Warning`/`DAW_WrnMsgSta`
   equivalent and its source (camera → cluster path).
3. Determine which message openpilot re-sends that carries the DAW warning field, and test
   forcing it to 0 — watching specifically for regressions in **adaptive high-beams, LKAS,
   and DAW settings** (the known ECU-conflict side effects).

## References

- sunnypilot forum: `/t/2023-2025-hyundai-palisade-kia-telluride/444` (DAW suppression
  snippet + ECU-conflict caveat; DAW_SysSta clarification).
- Kia Carnival owner's manual, "Driver Attention Warning (DAW)": break suggestion is
  suppressed for the first 4 minutes and after a prior break; popup at low attention level.
- Reddit `/r/kia` "Help: turn off the coffee cup" — confirms 2025+ HKG has no toggle for
  the take-a-break warning.
