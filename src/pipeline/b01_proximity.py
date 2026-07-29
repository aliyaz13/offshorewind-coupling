"""
Stage B01 - find coinciding Borehole / CPT locations within a tolerance.

Site-agnostic replacement for the three near-identical B01_proximity_{SITE}.py
scripts. Borehole locations can be an AGS4 or CSV file (per config); CPT is AGS4.
Runs headless: the map is SAVED to a PNG instead of a blocking plt.show().

  input : 04_.../locations/{SITE}/<borehole_file>  (ags or csv)
          04_.../locations/{SITE}/<cpt_file>       (ags)
  output: 04_.../{SITE}_Borehole_and_CPT_Coordinates_Matches.csv   (stage B02 map)
          04_.../{SITE}_map.png
"""
from __future__ import annotations

import argparse

import matplotlib
matplotlib.use("Agg")  # headless, no display needed
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

from .config import CONFIG, PATHS


def _load_cpt_locations(ags_path):
    from python_ags4 import AGS4
    tables, _ = AGS4.AGS4_to_dataframe(str(ags_path), get_line_numbers=False)
    loca = AGS4.convert_to_numeric(tables["LOCA"])
    return (list(loca.LOCA_NATE), list(loca.LOCA_NATN), list(loca.LOCA_ID))


def _load_borehole_locations(path, fmt: str):
    if fmt == "csv":
        df = pd.read_csv(path)
        return (list(df["Easting [m]"]), list(df["Northing [m]"]), list(df["Borehole"]))
    if fmt == "ags":
        return _load_cpt_locations(path)  # same LOCA structure
    raise ValueError(f"Unknown borehole_format: {fmt!r}")


def proximity(site: str) -> pd.DataFrame:
    site_cfg = CONFIG["sites"][site]
    prox = site_cfg["proximity"]
    tolerance = CONFIG.get("proximity_tolerance", 10)
    loc_dir = PATHS.proximity_locations(site)

    bore_e, bore_n, bore_id = _load_borehole_locations(
        loc_dir / prox["borehole_file"], prox["borehole_format"]
    )
    cpt_e, cpt_n, cpt_id = _load_cpt_locations(loc_dir / prox["cpt_file"])

    matches = []
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.scatter(bore_e, bore_n, c="green", marker="o", label="Boreholes")
    ax.scatter(cpt_e, cpt_n, c="red", marker="x", label="CPTs")

    for bid, bx, by in zip(bore_id, bore_e, bore_n):
        for cid, cx, cy in zip(cpt_id, cpt_e, cpt_n):
            dist = np.hypot(bx - cx, by - cy)
            if dist <= tolerance:
                matches.append((bid, cid, dist))
                ax.annotate(f"{bid} = {cid}", (bx, by), xytext=(0, 0),
                            textcoords="offset points", fontsize=5, color="blue")

    ax.set_xlabel("Easting [m]")
    ax.set_ylabel("Northing [m]")
    ax.set_aspect("equal", "box")
    ax.grid(ls="--")
    ax.legend(handles=[
        Line2D([0], [0], marker="o", color="w", markerfacecolor="green", label="BH", markersize=10),
        Line2D([0], [0], marker="x", color="red", label="CPT", markersize=10),
    ], title="Test Type")
    ax.set_title(f"{site}: Borehole & CPT locations within {tolerance} m")

    limits = site_cfg.get("plot_limits")
    if limits:
        ax.set_xlim(limits[0], limits[1])
        ax.set_ylim(limits[2], limits[3])

    PATHS.ensure()
    fig.savefig(PATHS.proximity_plot(site), dpi=150, bbox_inches="tight")
    plt.close(fig)

    return pd.DataFrame(matches, columns=["Borehole_ID", "CPT_ID", "Distance_m"])


def main(site: str) -> None:
    PATHS.ensure()
    df = proximity(site)
    out = PATHS.matches_file(site)
    df.to_csv(out, index=False)
    print(f"[B01] {site}: {len(df)} coinciding pairs -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Stage B01 - BH/CPT proximity")
    ap.add_argument("--site", required=True)
    args = ap.parse_args()
    main(args.site)
