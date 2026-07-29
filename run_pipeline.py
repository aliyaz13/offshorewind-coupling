#!/usr/bin/env python3
"""
Orchestrator - run the whole lab/CPT coupling pipeline end to end.

    A (process raw) -> B01 (proximity) -> B02 (couple) -> C (merge)

Examples
--------
    python run_pipeline.py                         # all sites, both approaches, all stages
    python run_pipeline.py --sites TNW             # just TNW
    python run_pipeline.py --approaches Appr02     # only refined coupling
    python run_pipeline.py --stages b02 c          # re-run coupling + merge only
    python run_pipeline.py --sites HKW NWZ --stages a

Everything else (paths, thresholds, per-site rules) comes from config.yaml.
Point config.yaml -> data_root at your data and nothing else needs editing.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

# allow "python run_pipeline.py" from the repo root without installing the pkg
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from pipeline import a_process, b01_proximity, b02_couple, c_merge  # noqa: E402
from pipeline.config import PATHS, approaches as cfg_approaches, sites as cfg_sites  # noqa: E402

ALL_STAGES = ["a", "b01", "b02", "c"]


def run(sites, approaches, stages, keep_going):
    PATHS.ensure()
    failures = []

    def step(label, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failures.append(label)
            print(f"  !! FAILED {label}: {exc}", file=sys.stderr)
            if not keep_going:
                traceback.print_exc()
                raise

    # A + B01 are per-site and independent of approach
    if "a" in stages:
        for s in sites:
            step(f"A/{s}", lambda s=s: a_process.main(s))
    if "b01" in stages:
        for s in sites:
            step(f"B01/{s}", lambda s=s: b01_proximity.main(s))
    # B02 is per (site, approach)
    if "b02" in stages:
        for a in approaches:
            for s in sites:
                step(f"B02/{s}/{a}", lambda s=s, a=a: b02_couple.main(s, a))
    # C is per approach (merges all sites)
    if "c" in stages:
        for a in approaches:
            step(f"C/{a}", lambda a=a: c_merge.main(a))

    print("\n" + ("=" * 60))
    if failures:
        print(f"Completed with {len(failures)} failure(s): {', '.join(failures)}")
        return 1
    print("Pipeline completed successfully.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites", nargs="+", default=cfg_sites(),
                    help=f"subset of {cfg_sites()} (default: all)")
    ap.add_argument("--approaches", nargs="+", default=cfg_approaches(),
                    help=f"subset of {cfg_approaches()} (default: all)")
    ap.add_argument("--stages", nargs="+", default=ALL_STAGES, choices=ALL_STAGES,
                    help="subset of stages to run (default: all)")
    ap.add_argument("--keep-going", action="store_true",
                    help="continue past a failing site/stage instead of aborting")
    args = ap.parse_args()

    # preserve config order regardless of CLI order
    sites = [s for s in cfg_sites() if s in args.sites]
    approaches = [a for a in cfg_approaches() if a in args.approaches]
    stages = [s for s in ALL_STAGES if s in args.stages]

    print(f"sites={sites}  approaches={approaches}  stages={stages}")
    raise SystemExit(run(sites, approaches, stages, args.keep_going))


if __name__ == "__main__":
    main()
