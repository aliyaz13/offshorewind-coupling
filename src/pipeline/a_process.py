"""
Stage A - turn raw lab data into a cleaned per-site soil-parameters CSV.

  output: 03_lab_data_cleaned/{SITE}_soil_parameters.csv   (stage B02 soil input)

Two kinds of site processor (selected by `a_process` in config):
  * "hkw_csv"  : merge the 4 pre-cleaned HKW CSVs (implemented here).
  * "nwz_xlsx" / "tnw_xlsx" : the heavy .xlsx scrapers. Their large, site-
    specific parsing logic is preserved untouched in sites/A_process_*_raw.py;
    we only inject paths via the OWC_DATA_ROOT env var and run them.
"""
from __future__ import annotations

import argparse
import os
import runpy
from pathlib import Path

import pandas as pd

from .config import CONFIG, PATHS

_SITES_DIR = Path(__file__).resolve().parent / "sites"
_HEAVY_SCRIPT = {
    "nwz_xlsx": _SITES_DIR / "A_process_NWZ_raw.py",
    "tnw_xlsx": _SITES_DIR / "A_process_TNW_raw.py",
}


def _process_hkw() -> pd.DataFrame:
    """Merge the four pre-cleaned HKW CSVs on Borehole + Depth."""
    raw = PATHS.raw_site("HKW")
    df_cd = pd.read_csv(raw / "HKW_CD_cleaned.csv")
    df_cu = pd.read_csv(raw / "HKW_CU_cleaned.csv")
    df_ds = pd.read_csv(raw / "HKW_DirectShear_cleaned.csv")
    df_oed = pd.read_csv(raw / "HKW_Oedometer_cleaned.csv")

    df_cd = df_cd.rename(columns={"sampling_name(-)": "Borehole"})
    df_cu = df_cu.rename(columns={"sampling_name(-)": "Borehole"})
    df_ds = df_ds.rename(columns={"depth (m)": "Depth (m)"})

    for df in (df_cd, df_cu, df_ds, df_oed):
        df["Borehole"] = df["Borehole"].astype(str).str.strip()
        df["Depth (m)"] = pd.to_numeric(df["Depth (m)"], errors="coerce")
        df.dropna(subset=["Borehole", "Depth (m)"], inplace=True)

    merged = df_cd
    for other in (df_cu, df_ds, df_oed):
        merged = pd.merge(merged, other, on=["Borehole", "Depth (m)"], how="outer")

    merged = merged.sort_values(by=["Borehole", "Depth (m)"])
    merged.drop("Sample ID", axis=1, inplace=True, errors="ignore")
    merged.rename(columns={"Borehole": "sampling_name (-)", "Depth (m)": "depth (m)"},
                  inplace=True)
    return merged


def _run_heavy(kind: str) -> None:
    """Run a preserved .xlsx scraper, feeding it paths via OWC_DATA_ROOT."""
    script = _HEAVY_SCRIPT[kind]
    env_prev = os.environ.get("OWC_DATA_ROOT")
    os.environ["OWC_DATA_ROOT"] = str(PATHS.root)
    try:
        runpy.run_path(str(script), run_name="__main__")
    finally:
        if env_prev is None:
            os.environ.pop("OWC_DATA_ROOT", None)
        else:
            os.environ["OWC_DATA_ROOT"] = env_prev


def main(site: str) -> None:
    PATHS.ensure()
    kind = CONFIG["sites"][site]["a_process"]
    if kind == "hkw_csv":
        df = _process_hkw()
        out = PATHS.cleaned_file(site)
        df.to_csv(out, index=False)
        print(f"[A]  {site}: {len(df)} rows -> {out}")
    elif kind in _HEAVY_SCRIPT:
        _run_heavy(kind)
        print(f"[A]  {site}: ran {_HEAVY_SCRIPT[kind].name} -> {PATHS.cleaned_file(site)}")
    else:
        raise ValueError(f"Unknown a_process kind: {kind!r}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Stage A - process raw lab data")
    ap.add_argument("--site", required=True)
    args = ap.parse_args()
    main(args.site)
