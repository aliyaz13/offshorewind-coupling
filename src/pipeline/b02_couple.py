"""
Stage B02 - couple cleaned soil samples to the nearest CPT reading.

One site-agnostic implementation replaces the 6 near-identical per-site copies.
Approach ("Appr01" | "Appr02") and site are parameters; everything else comes
from config.yaml.

  input : 03_lab_data_cleaned/{SITE}_soil_parameters.csv   (stage A)
          01_cpt/<cpt_merged for site>                      (given)
          04_.../{SITE}_..._Matches.csv                     (stage B01)
  output: 05_merge_cpt_lab/{SITE}_soil_cpt_{approach}.csv
"""
from __future__ import annotations

import argparse

import pandas as pd

from . import common
from .config import CONFIG, PATHS


def couple(site: str, approach: str) -> pd.DataFrame:
    site_cfg = CONFIG["sites"][site]
    appr_cfg = CONFIG["coupling"][approach]

    cpt = pd.read_csv(PATHS.cpt_merged(site))
    soil = pd.read_csv(PATHS.cleaned_file(site))
    mapping = pd.read_csv(PATHS.matches_file(site))

    cpt["depth (m)"] = pd.to_numeric(cpt["depth (m)"], errors="coerce")
    soil["depth (m)"] = pd.to_numeric(soil["depth (m)"], errors="coerce")

    normalizer = common.soil_normalizer(site_cfg["id_normalization"])
    soil["bh_id"] = soil["sampling_name (-)"].apply(normalizer)
    cpt["bh_id"] = cpt["ID"].apply(common.normalize_cpt_id)

    if approach == "Appr01":
        cols = ["CPT_ID", "qc (MPa)", "fs (kPa)", "Rf (%)", "u2 (kPa)"]
        soil[cols] = soil.apply(
            common.get_nearest_cpt, axis=1, cpt_df=cpt,
            threshold=appr_cfg["threshold"],
        )
    elif approach == "Appr02":
        cols = ["CPT_ID", "qc (MPa)", "fs (kPa)", "Rf (%)", "u2 (kPa)", "CPT_depth (m)"]
        soil[cols] = soil.apply(
            common.get_nearest_cpt_refined, axis=1, cpt_df=cpt,
            threshold=appr_cfg["threshold"], cov_limit=appr_cfg["cov_limit"],
        )
    else:
        raise ValueError(f"Unknown approach: {approach!r}")

    # attach the CPT<->BH horizontal distance from the proximity mapping
    soil = soil.merge(
        mapping[["Borehole_ID", "CPT_ID", "Distance_m"]],
        left_on=["sampling_name (-)", "CPT_ID"],
        right_on=["Borehole_ID", "CPT_ID"],
        how="left",
    )
    soil.drop(columns=["Borehole_ID", "bh_id"], inplace=True, errors="ignore")

    if approach == "Appr02":
        # derived, human-readable coupling-quality columns
        soil["Vertical_Depth_Difference (m)"] = soil["CPT_depth (m)"] - soil["depth (m)"]
        soil.rename(columns={"Distance_m": "CPT_to_BH_Distance (m)"}, inplace=True)
    else:
        soil.rename(columns={"Distance_m": "CPT_to_BH_Distance (m)"}, inplace=True)

    soil["site"] = site
    soil["coupling_approach"] = approach
    return soil


def main(site: str, approach: str) -> None:
    PATHS.ensure()
    df = couple(site, approach)
    out = PATHS.coupled_file(site, approach)
    df.to_csv(out, index=False)
    print(f"[B02] {site} / {approach}: {len(df)} rows -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Stage B02 - couple soil with CPT")
    ap.add_argument("--site", required=True)
    ap.add_argument("--approach", required=True, choices=["Appr01", "Appr02"])
    args = ap.parse_args()
    main(args.site, args.approach)
