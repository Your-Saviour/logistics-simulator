# SIMU-75 layout correction proposal

Status: approved by the user and applied to shared/native catalogs and fleet
navigation geometry. No deployment or live-volume cutover has been performed.

The prior layout had overlapping outbound trucks and manufacturing equipment,
29 unsafe service sweeps, and truck/manufacturing bays whose rendered loads
intersected. The initial correction (outbound trucks east, machines south) removes
service-route failures but leaves 80 overlapping load pairs. This proposal also
corrects bay spacing while preserving all 800 endpoint IDs and all elevations.

| Change | Proposed geometry | Position records changed |
| --- | --- | ---: |
| Eight truck groups | First-slot z = −22, −10, 2, 14; slot pitch 1.1 m | 64 |
| Four outbound trucks | x = 22; incoming x remains −43 | Included above |
| Four manufacturing cells | Inputs z = −6 + 1.1 × (slot−1); outputs z = 2 + 1.1 × (slot−1) | 28 |
| Manufacturing machines | Visual group z = input01 z + 5.35; floor footprint z = −1.5…0.75 | Four geometry groups |
| Shipping dock 01 | x = 17.2, y/z unchanged; access unchanged | 1 |
| Finished receiving docks | Service from north at z = 4.5; endpoint positions unchanged | 0 |

Total: **93 endpoint positions**, four machine groups, and proposed service poses
listed in the final audit. Truck access references remain unchanged. The additional
shipping dock move removes two 0.14 m load gaps; the proposed lateral gap is 0.20 m.

The robot remains 0.85 × 1.05 m with 0.15 m obstacle clearance. Loads remain
0.80 × 0.72 × 0.86 m. Shelf approaches retain the documented side. Trucks use the
open east side to avoid the solid west sidewall. Service offsets are at most
1.8 m; full robot turning envelopes are checked. Some truck approaches need the
1.8 m offset to provide turning clearance around the full truck footprint.

See [candidate.json](candidate.json) for explicit deltas and
[audit-final.json](audit-final.json) for the approved coordinate/service manifest
and [applied-audit.json](applied-audit.json) for verification of the current catalog. [layout.svg](layout.svg) compares the
floor geometry. Existing IDs preserve native placement references. Active operations require a
separately authorized cutover; existing volumes were not changed.

Final guarded validation completed with **800/800 valid services, 800/800 approach
and return routes, 16/16 safe connected parking poses, zero load placement
clearance conflicts and zero load/machine intersections**. The minimum physical
load gap is 0.24 m. These are floor and loaded-placement results; fork insertion
mechanics remain explicitly described below.

The validator imports the actual fleet `Navigation` and `Worker.service_pose`,
audits the current approved catalog when its layout revision is present (and
constructs proposal copies only for a baseline catalog), checks all 800 endpoints and all pairwise loaded placements, and
uses exact navigation edge predicates for common-parking approach/return scans.
No foreign machine or equipment is exempted from a fork sweep. Own rack/truck
support contact is intentional; it does not authorize a solid frontbeam crossing.

Shelf transfer requires an explicit raised stage: fork height at least shelf y
+ 0.26 m gives 0.15 m clearance above the current frontbeam. A 0.72 m load then
has 0.39 m clearance below the next shelf underdeck. Initial fork insertion needs
an explicit pallet/fork pocket model; this proposal records that rendering and
stage requirement for implementation after layout approval. This is a bounded
mechanical modelling limitation, not evidence of current collision-free forks.

Reproduce the proposal audit inside Docker, retaining the default disk reserve:

```sh
python3 scripts/docker_guard.py --wait --label fleet-layout-proposal -- \
  docker compose -f apps/fleet/test.compose.yml run --rm --no-deps \
  -v "$PWD/docs/proposals/simu75-layout:/proposal:ro" \
  tests python /proposal/validate.py
```

The 100 ms scheduler target is soft following user steering. Initial existing-floor
single loaded-route trials took 54.7/13.5/20.6 ms inbound, 118.0/31.5/32.0 ms
shelving, 24.5/5.0/6.1 ms manufacturing, and 642.2/232.4/137.5 ms outbound. These
are three trials per route with reused geometry caches, not a 16-robot/256-job
scheduler p95 measurement. No collision envelope was reduced for performance.
