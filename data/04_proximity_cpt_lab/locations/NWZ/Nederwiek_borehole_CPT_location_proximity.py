# -*- coding: utf-8 -*-
"""
Created on Fri Sep  5 14:16:39 2025

@author: niego

This script loads Borehole (BH) and Cone Penetration Test (CPT) location data 
from AGS4 files, plots them on a 2D map, and identifies coinciding locations 
(within a user-defined tolerance). It outputs both a visualization and 
a summary table of matched Borehole–CPT pairs.
"""

# %% Import Libraries
from python_ags4 import AGS4
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

# %% 0. Configuration

# Define color mapping for test types
color_map = {
    "PCPT": "red",   # Piezocone CPT
    "SCPT": "red",   # Seismic CPT
    "TCPT": "red",   # Thermal CPT
    "BH": "green"    # Boreholes
}

# Distance threshold (meters) to consider two locations as coinciding
tolerance = 10

# Paths to AGS4 files
dir_boreholes = r"C:\Users\niego\Nextcloud\Shared\Master's thesis_Ali Yaz\02_WorkPackage1\data\soil-parameters\coupling-cpt\CPT_BH_Proximity\Nederwiek\NWZ_BH.ags"
dir_cpt = r"C:\Users\niego\Nextcloud\Shared\Master's thesis_Ali Yaz\02_WorkPackage1\data\soil-parameters\coupling-cpt\CPT_BH_Proximity\Nederwiek\NWZ_CPT.ags"


# %% 1. Load Borehole Data
bore_tables, bore_headings = AGS4.AGS4_to_dataframe(
    dir_boreholes, get_line_numbers=False
)
LOCA_boreholes = AGS4.convert_to_numeric(bore_tables["LOCA"])

# Extract coordinates and IDs
bore_east = list(LOCA_boreholes.LOCA_NATE)
bore_north = list(LOCA_boreholes.LOCA_NATN)
bore_ids = list(LOCA_boreholes.LOCA_ID)

# Assign colors by suffix in ID
bore_colors = [
    color_map.get(item.split("-")[-1], "black") for item in bore_ids
]


# %% 2. Load CPT Data
cpt_tables, cpt_headings = AGS4.AGS4_to_dataframe(
    dir_cpt, get_line_numbers=False
)
LOCA_cpt = AGS4.convert_to_numeric(cpt_tables["LOCA"])

# Extract coordinates and IDs
cpt_east = list(LOCA_cpt.LOCA_NATE)
cpt_north = list(LOCA_cpt.LOCA_NATN)
cpt_ids = list(LOCA_cpt.LOCA_ID)

# Assign colors by suffix in ID
cpt_colors = [
    color_map.get(item.split("-")[-1], "black") for item in cpt_ids
]


# %% 3. Plot Boreholes and CPTs
fig, ax = plt.subplots(figsize=(8, 12))

# Plot boreholes (circles)
ax.scatter(bore_east, bore_north, c=bore_colors, marker="o", label="Boreholes")

# Plot CPTs (crosses)
ax.scatter(cpt_east, cpt_north, c=cpt_colors, marker="x", label="CPTs")

# Axis formatting
ax.set_xlabel("Easting [m]")
ax.set_ylabel("Northing [m]")
ax.set_aspect("equal", "box")
ax.grid(ls="--")

# Custom legend with marker styles
legend_elements = [
    Line2D([0], [0], marker="o", color="w", markerfacecolor="green",
           label="BH", markersize=10),
    Line2D([0], [0], marker="x", color="red",
           label="CPT (PCPT/SCPT/TCPT)", markersize=10)
]
ax.legend(handles=legend_elements, title="Test Type")


# %% 4. Find coinciding locations (within tolerance)
matches = []

for bid, bx, by in zip(bore_ids, bore_east, bore_north):
    for cid, cx, cy in zip(cpt_ids, cpt_east, cpt_north):
        # Calculate Euclidean distance between BH and CPT
        dist = np.sqrt((bx - cx) ** 2 + (by - cy) ** 2)

        if dist <= tolerance:
            # Save the match for summary table
            matches.append((bid, cid, dist))

            # Annotate the plot with both IDs
            ax.annotate(f"{bid} = {cid}",
                        (bx, by),
                        xytext=(0, 0),
                        textcoords="offset points",
                        fontsize=5,
                        color="blue")

plt.title("Borehole and CPT Locations with Coinciding IDs")
plt.show()


# %% 5. Build summary table & histogram

df_matches = pd.DataFrame(matches,
                          columns=["Borehole_ID", "CPT_ID", "Distance_m"])

print("\nSummary of coinciding Boreholes and CPTs (within tolerance):")
print(df_matches)

# Create histogram for matching IDs distance
plt.figure(figsize=(10,6))
plt.hist(df_matches['Distance_m'], bins=60, color='skyblue', edgecolor='black', alpha=0.7)
plt.xlabel("Distance (m)", fontsize=12)
plt.ylabel("Frequency", fontsize=12)
plt.title("Histogram of Distances", fontsize=14)
plt.grid(axis='y', linestyle='--', alpha=0.5)
plt.show()

# %% 6. Export

df_matches.to_csv(r"C:\Users\niego\Nextcloud\Shared\Master's thesis_Ali Yaz\02_WorkPackage1\data\soil-parameters\coupling-cpt\CPT_BH_Proximity\Nederwiek\NWZ_Borehole_and_CPT_Coordinates_Matches.csv")

