"""
Shared coupling logic - extracted verbatim from the per-site B02 scripts so it
lives in ONE place instead of being copy-pasted into every file.

  * normalize_cpt_id / normalize_soil_id / normalize_soil_id_nederwiek
  * get_nearest_cpt         -> used by approach "Appr01"
  * get_nearest_cpt_refined -> used by approach "Appr02"
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# ID normalization
# ---------------------------------------------------------------------------
def normalize_cpt_id(cpt_id: str) -> str:
    """
    Normalize CPT IDs (HKW, TNW, Nederwiek).
      TNW001-PCPT    -> TNW001
      TNW001-PCPT-A  -> TNW001-A
    """
    parts = str(cpt_id).split("-")
    if len(parts) == 2:
        return parts[0]
    if len(parts) == 3:
        return f"{parts[0]}-{parts[2]}"
    return str(cpt_id)


def normalize_soil_id(soil_id: str) -> str:
    """
    Default soil-ID normalization (HKW, TNW).
      TNW001-BH     -> TNW001
      TNW001-BH-A   -> TNW001-A
    """
    parts = str(soil_id).split("-")
    if len(parts) == 2:
        return parts[0]
    if len(parts) == 3:
        return f"{parts[0]}-{parts[2]}"
    return str(soil_id)


def normalize_soil_id_nederwiek(soil_id: str) -> str:
    """
    Special normalization for Nederwiek (NWZ) files.
      NWZ-BH-001    -> NWZ001
      NWZ-BH-001-A  -> NWZ001-A
    """
    parts = str(soil_id).split("-")
    if len(parts) == 3:
        return f"{parts[0]}-{parts[2]}"
    if len(parts) == 4:
        return f"{parts[0]}-{parts[2]}-{parts[3]}"
    return str(soil_id)


def soil_normalizer(rule: str):
    """Return the soil-ID normalizer named by config (`id_normalization`)."""
    return {
        "default": normalize_soil_id,
        "nederwiek": normalize_soil_id_nederwiek,
    }[rule]


# ---------------------------------------------------------------------------
# Approach 01 - simple nearest CPT within a depth threshold
# ---------------------------------------------------------------------------
def get_nearest_cpt(row, cpt_df: pd.DataFrame, threshold: float = 0.40) -> pd.Series:
    """
    For each soil sample, find the nearest CPT measurement within `threshold`.
    Prefers candidates that have BOTH qc and fs; otherwise falls back to the
    single nearest row within threshold.

    Returns: [CPT_ID, qc (MPa), fs (kPa), Rf (%), u2 (kPa), CPT_depth (m)]
    """
    idx = ["CPT_ID", "qc (MPa)", "fs (kPa)", "Rf (%)", "u2 (kPa)", "CPT_depth (m)"]

    bh_cpt = cpt_df[cpt_df["bh_id"] == row["bh_id"]].copy()
    if bh_cpt.empty or pd.isna(row["depth (m)"]):
        return pd.Series([np.nan] * 6, index=idx)

    bh_cpt["depth_diff"] = (bh_cpt["depth (m)"] - row["depth (m)"]).abs()
    if bh_cpt["depth_diff"].isna().all():
        return pd.Series([np.nan] * 6, index=idx)

    candidates = bh_cpt[bh_cpt["depth_diff"] <= threshold].copy()
    if candidates.empty:
        return pd.Series([np.nan] * 6, index=idx)

    complete = candidates[candidates["qc (MPa)"].notna() & candidates["fs (MPa)"].notna()]
    if not complete.empty:
        nearest = complete.loc[complete["depth_diff"].idxmin()]
    else:
        nearest = candidates.loc[candidates["depth_diff"].idxmin()]
    
    return pd.Series([
        nearest["ID"],
        nearest["qc (MPa)"],
        nearest["fs (MPa)"] * 1000 if pd.notna(nearest["fs (MPa)"]) else np.nan,
        nearest["Rf (%)"],
        nearest["u2 (MPa)"] * 1000 if pd.notna(nearest["u2 (MPa)"]) else np.nan,
        nearest["depth (m)"],
    ], index=idx)


# ---------------------------------------------------------------------------
# Approach 02 - refined: depth window + qc stability (CoV) + completeness
# ---------------------------------------------------------------------------
def get_nearest_cpt_refined(row, cpt_df: pd.DataFrame,
                            threshold: float = 0.25,
                            cov_limit: float = 0.30) -> pd.Series:
    """
    Refined nearest-CPT matching:
      1. Restrict to CPT rows within `threshold` of the soil-sample depth.
      2. Stability: if CoV of qc in that window > `cov_limit`, reject (too noisy).
      3. Among the window, take the CLOSEST row that has complete qc + fs.

    Returns: [CPT_ID, qc (MPa), fs (kPa), Rf (%), u2 (kPa), CPT_depth (m)]
    """
    idx = ["CPT_ID", "qc (MPa)", "fs (kPa)", "Rf (%)", "u2 (kPa)", "CPT_depth (m)"]

    bh_cpt = cpt_df[cpt_df["bh_id"] == row["bh_id"]].copy()
    if bh_cpt.empty or pd.isna(row["depth (m)"]):
        return pd.Series([np.nan] * 6, index=idx)

    bh_cpt["depth_diff"] = (bh_cpt["depth (m)"] - row["depth (m)"]).abs()
    candidates = bh_cpt[bh_cpt["depth_diff"] <= threshold].sort_values("depth_diff")
    if candidates.empty:
        return pd.Series([np.nan] * 6, index=idx)

    qc_values = candidates["qc (MPa)"].dropna()
    if len(qc_values) > 1:
        cv = qc_values.std() / qc_values.mean()
        if cv > cov_limit:
            return pd.Series([np.nan] * 6, index=idx)

    complete = candidates.dropna(subset=["qc (MPa)", "fs (MPa)"])
    if complete.empty:
        return pd.Series([np.nan] * 6, index=idx)
    best = complete.iloc[0]

    return pd.Series([
        best["ID"],
        best["qc (MPa)"],
        best["fs (MPa)"] * 1000 if pd.notna(best["fs (MPa)"]) else np.nan,
        best["Rf (%)"],
        best["u2 (MPa)"] * 1000 if pd.notna(best["u2 (MPa)"]) else np.nan,
        best["depth (m)"],
    ], index=idx)
