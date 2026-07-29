"""
Stage C - merge every per-site coupled file for a given approach into one
dataset.

  input : 05_merge_cpt_lab/*_soil_cpt_{approach}.csv   (stage B02 outputs)
  output: 05_merge_cpt_lab/merged_soil_cpt_{approach}.csv

Fixes over the original C_merge_all.py:
  * globs the ACTUAL stage-B02 output folder (was a folder nothing wrote to)
  * puts known columns first but KEEPS every other column instead of silently
    dropping ones whose names drifted (e.g. the Appr02 distance / depth-diff
    columns).
"""
from __future__ import annotations

import argparse

import pandas as pd

from .config import PATHS

# Preferred leading column order. Columns not in this list are kept and
# appended afterwards (nothing is dropped).
PREFERRED_COLS = [
    "site", "coupling_approach",
    "sampling_name (-)", "depth (m)",
    "CPT_ID", "qc (MPa)", "fs (kPa)", "Rf (%)", "u2 (kPa)",
    "CPT_depth (m)", "Vertical_Depth_Difference (m)", "CPT_to_BH_Distance (m)",
    "gamma (kN/m3)", "gamma_d (kN/m3)", "Eoed (MPa)", "OCR (-)", "e0 (-)",
    "phi_CD (degree)", "cohesion_CD (kPa)",
    "phi_DSS (degree)", "cohesion_DSS (kPa)",
    "phi_RS_peak (degree)", "phi_RS_residual (degree)",
    "phi_SB (degree)", "cohesion_SB (kPa)",
    "su_CU_remoulded (kPa)", "su_CU_undisturbed (kPa)", "su_CUe_undisturbed (kPa)",
    "su_DSS (kPa)", "su_UU_remoulded (kPa)", "su_UU_undisturbed (kPa)",
    "water_content (%)", "torvane (kPa)", "pocket_penetrometer (kPa)",
    "E50ref (MPa)", "E50ref_m_parameter (-)",
    "source_files",
]


def _order_columns(df: pd.DataFrame) -> pd.DataFrame:
    lead = [c for c in PREFERRED_COLS if c in df.columns]
    rest = [c for c in df.columns if c not in lead]
    return df.reindex(columns=lead + rest)


def merge(approach: str) -> pd.DataFrame:
    files = sorted(PATHS.merge.glob(f"*_soil_cpt_{approach}.csv"))
    if not files:
        raise FileNotFoundError(
            f"No coupled files found: {PATHS.merge}/*_soil_cpt_{approach}.csv"
        )
    dfs = [pd.read_csv(f, sep=",", engine="python") for f in files]
    merged = pd.concat(dfs, axis=0, ignore_index=True, sort=False)
    return _order_columns(merged)


def main(approach: str) -> None:
    PATHS.ensure()
    merged = merge(approach)
    out = PATHS.merged_file(approach)
    merged.to_csv(out, index=False)
    print(f"[C]  {approach}: {len(merged)} rows -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Stage C - merge coupled site files")
    ap.add_argument("--approach", required=True, choices=["Appr01", "Appr02"])
    args = ap.parse_args()
    main(args.approach)
