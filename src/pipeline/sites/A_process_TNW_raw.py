"""
Geotechnical Laboratory Data Processor
Created: September 2025
Updated: January 2026

KEY QC FEATURES & PARAMETERS:
---------------------------------------------------------------------------------------
1. STATISTICAL QC (CAPPED): 
   - Function: safe_average_with_scatter_control
   - Parameter: 10% threshold. If (Max - Min) / Mean > 0.10, index property is returned as NaN.
   - Purpose: Eliminates outliers in water content, density, and void ratio for thesis integrity.

2. E50ref OPTIMIZATION (STRICT):
   - Logic: Janbu Power Law normalization at p_ref = 100 kPa.
   - REQUIREMENT: Minimum of 3 CD/CID specimens required per borehole/depth to validate COV.
   - SELECTION: Chooses m (0.50, 0.75, 1.00) with the lowest COV, provided COV < 20%.

3. ATTRACTION SAFETY (a):
   - Formula: a = cohesion / tan(phi)
   - SAFETY CAP: If phi' <= 2.0 degrees, 'a' is set to 0 to avoid division by zero errors 
     and unphysically high stiffness normalization.

4. ANISOTROPY DETECTION:
   - Identifies 'CUe' (Extension) tests automatically if deviator stress (qf) is negative.
---------------------------------------------------------------------------------------
@author: niego
"""
# %%
from pathlib import Path
import pandas as pd
import re
import numpy as np
# %%
# ==============================================================================
# 1. DATA EXTRACTION & CLEANING UTILITIES
# ==============================================================================

def clean_value(val):
    """Remove units in [ ] and strip text."""
    if pd.isna(val): return None
    val = str(val)
    val = re.sub(r"\[.*?\]", "", val)
    return val.strip()

def normalize_depth_column(df, depth_col="depth"):
    """Convert depth intervals (e.g. '42.25 - 42.75') into numeric averages."""
    def parse_depth(val):
        if pd.isna(val): return np.nan
        s = str(val).strip()
        if re.match(r"^\s*\d+(\.\d+)?\s*-\s*\d+(\.\d+)?\s*$", s):
            parts = re.split(r"-", s)
            try:
                nums = [float(p) for p in parts]
                return sum(nums) / len(nums)
            except: return np.nan
        try: return float(s)
        except: return np.nan
    df[depth_col] = df[depth_col].apply(parse_depth)
    return df

def clean_test_type(test_str):
    """Map raw laboratory strings to standardized geotechnical test types."""
    if pd.isna(test_str): return test_str
    s = str(test_str).upper()
    if 'CAUCBE' in s: return 'CU + BE'
    if 'CAUE' in s or 'CIUE' in s: return 'CUe'
    if 'CAU' in s or 'CIU' in s: return 'CU'
    if 'CID' in s: return 'CD'
    if any(k in s for k in ['RS-', 'RS_RS', 'ISO', 'ICPR', 'ICRS']): return 'RS'
    if 'DSS' in s: return 'DSS'
    if 'SB' in s: return 'SB'
    if 'UU' in s: return 'UU'
    if 'UNCONSOLIDATED_UNDRAINED' in s: return 'UU'
    return test_str

def identify_extension_tests(row):
    """Identifies Extension tests based on negative Peak Deviator Stress (qf)."""
    current_test = str(row.get("test_type", "")).upper()
    qf_col = [c for c in row.index if 'deviator_stress_peak_qf' in c]
    if qf_col:
        qf_val = row[qf_col[0]]
        try:
            # Flatten list if aggregated
            val = qf_val[0] if isinstance(qf_val, (list, np.ndarray)) else qf_val
            if pd.notna(val) and float(val) < 0:
                if any(k in current_test for k in ["CU", "CAU", "CIU"]): return "CUe"
        except: pass
    return current_test

def get_specimen_columns(df):
    """Detects specimen indices for 'Side-by-Side' triaxial Excel layouts."""
    sample_info = df.iloc[:20].fillna("").astype(str)
    detected = {}
    for col_idx in range(1, df.shape[1]): 
        column_text = " ".join(sample_info[col_idx].tolist()).upper()
        if "UNDISTURBED" in column_text: detected[col_idx] = "Undisturbed"
        elif "REMOULDED" in column_text: detected[col_idx] = "Remoulded"
        elif "SPECIMEN" in column_text:
            match = re.search(r"SPECIMEN\s*(\d+)", column_text)
            detected[col_idx] = f"Specimen {match.group(1)}" if match else f"Specimen {col_idx}"
    if not detected: detected[1] = "Specimen 1"
    return detected

def aggregate_specimens(df, borehole_col, depth_col):
    """Collapses multiple specimens into single rows using lists."""
    def agg_func(series):
        return series.tolist() if len(series) > 1 else series.iloc[0]
    return df.groupby([borehole_col, depth_col], as_index=False).agg(
        {col: agg_func for col in df.columns if col not in [borehole_col, depth_col]}
    )

def clean_numeric_list(x):
    """Cleans lists of numeric values, removing NaNs and placeholders. i.e. [nan, '-']"""
    if isinstance(x, (list, tuple)):
        cleaned = [
            float(v) for v in x
            if pd.notna(v) and v != "-"
        ]
        return cleaned if cleaned else pd.NA
    return x

# %%
# ==============================================================================
# 2. ANALYTICAL FUNCTIONS (QC & STIFFNESS)
# ==============================================================================

def safe_average_with_scatter_control(val):
    """CAPPED: Returns NaN if (Max-Min)/Mean > 10% scatter between specimens."""
    def clean_to_floats(items):
        iterable = items if isinstance(items, (list, np.ndarray)) else [items]
        cleaned = []

        for x in iterable:
            if pd.isna(x):
                continue
            if isinstance(x, str) and x.strip() in {"", "-", "--", "n/a", "NA"}:
                continue
            try:
                cleaned.append(float(x))
            except (ValueError, TypeError):
                continue

        return cleaned

    data = clean_to_floats(val)
    if not data:
        return np.nan
    if len(data) == 1:
        return data[0]

    data_mean = sum(data) / len(data)
    if data_mean == 0:
        return 0.0

    if (max(data) - min(data)) / data_mean > 0.10:
        return np.nan

    return data_mean


def split_shear_parameters_robust(row):
    """Separates phi/cohesion into CD and SB categories for plotting."""
    res = {'phi_CD (degree)': np.nan, 'cohesion_CD (kPa)': np.nan,
           'phi_SB (degree)': np.nan, 'cohesion_SB (kPa)': np.nan}
    
    def to_list(v): return list(v) if isinstance(v, (list, np.ndarray)) else [v]
    
    tests = to_list(row.get('test_type', []))
    phi_vals = to_list(row.get('phi (degree)', []))
    coh_vals = to_list(row.get('cohesion (kPa)', []))

    for i, t in enumerate(tests):
        t_type = str(t).upper().strip()
        phi = float(phi_vals[i]) if i < len(phi_vals) and pd.notna(phi_vals[i]) else np.nan
        coh = float(coh_vals[i]) if i < len(coh_vals) and pd.notna(coh_vals[i]) else np.nan

        if t_type in ["CD", "CID"]:
            if pd.notna(phi): res['phi_CD (degree)'] = phi
            if pd.notna(coh): res['cohesion_CD (kPa)'] = coh
        elif t_type == "SB":
            if pd.notna(phi): res['phi_SB (degree)'] = phi
            if pd.notna(coh): res['cohesion_SB (kPa)'] = coh
    return pd.Series(res)

def extract_su_dimensions(row):
    """Calculates su for UU, CU, and CUe (abs used for extension)."""
    res = {'su_UU_undisturbed (kPa)': np.nan, 'su_UU_remoulded (kPa)': np.nan,
           'su_CU_undisturbed (kPa)': np.nan, 'su_CU_remoulded (kPa)': np.nan,
           'su_CUe_undisturbed (kPa)': np.nan}

    def to_list(v): return list(v) if isinstance(v, (list, np.ndarray)) else [v]
    
    tests = [str(x).upper() for x in to_list(row.get('test_type', []))]
    samples = [str(x).lower() for x in to_list(row.get('sample_type', []))]
    qf_vals = to_list(row.get('secant_modulus_e50_deviator_stress_peak_qf (kPa)', []))
    uu_vals = to_list(row.get('undrained_shear_strength (kPa)', []))

    for i, t in enumerate(tests):
        s = samples[i] if i < len(samples) else ""
        qf = float(qf_vals[i]) if i < len(qf_vals) and pd.notna(qf_vals[i]) else np.nan
        su_calc = abs(qf) / 2.0 if pd.notna(qf) else np.nan
        
        if "UU" in t:
            val = uu_vals[i] if (i < len(uu_vals) and pd.notna(uu_vals[i])) else su_calc
            if "remoulded" in s: res['su_UU_remoulded (kPa)'] = val
            else: res['su_UU_undisturbed (kPa)'] = val
        elif any(k in t for k in ["CU", "CAUC"]):
            if "CUE" in t or "CAUE" in t: res['su_CUe_undisturbed (kPa)'] = su_calc
            else:
                if "remoulded" in s: res['su_CU_remoulded (kPa)'] = su_calc
                else: res['su_CU_undisturbed (kPa)'] = su_calc
    return pd.Series(res)

def optimize_m_parameter(row):
    """
    Stiffness Normalization (Janbu). 
    STRICT REQUIREMENT: >= 3 Specimens. 
    SAFETY: Capped 'a' for low phi.
    """
    p_ref, m_values = 100.0, [0.5, 0.75, 1.0]
    output = {}
    
    def to_list(v): return list(v) if isinstance(v, (list, np.ndarray)) else [v]
    
    tests = to_list(row.get('test_type', []))
    e50_list = to_list(row.get('secant_modulus_e50 (kPa)', []))
    s3_list = to_list(row.get('secant_modulus_e50_sigma_eff_3 (kPa)', []))

    cd_indices = [i for i, t in enumerate(tests) if str(t).upper() in ['CD', 'CID']]
    e50_measured = np.array([float(e50_list[i]) for i in cd_indices if i < len(e50_list) and pd.notna(e50_list[i])])
    s3_eff = np.array([float(s3_list[i]) for i in cd_indices if i < len(s3_list) and pd.notna(s3_list[i])])

    # Attraction Safety Cap (phi > 2.0)
    phi = float(row.get('phi_CD (degree)', 0))
    coh = float(row.get('cohesion_CD (kPa)', 0))
    a = coh / np.tan(np.radians(phi)) if phi > 2.0 else 0 

    if len(e50_measured) >= 3:
        cov_results, e50_ref_means = {}, {}
        for m in m_values:
            m_str = str(m).replace('.', '_')
            e50_ref_set = e50_measured / ((s3_eff + a) / (p_ref + a))**m
            mean_val, std_val = np.mean(e50_ref_set), np.std(e50_ref_set)
            cov = (std_val / mean_val * 100) if mean_val != 0 else np.nan
            output[f'E50ref_m_{m_str}'] = mean_val
            output[f'COV_E50_ref_m_{m_str}'] = cov
            cov_results[m], e50_ref_means[m] = cov, mean_val

        valid_m = {m: c for m, c in cov_results.items() if pd.notna(c) and c < 20}
        if valid_m:
            best_m = min(valid_m, key=valid_m.get)
            output.update({'chosen_m': best_m, 'chosen_COV (%)': valid_m[best_m], 'chosen_E50ref (kPa)': e50_ref_means[best_m]})
        else: output.update({'chosen_m': np.nan, 'chosen_COV (%)': np.nan, 'chosen_E50ref (kPa)': np.nan})
    else:
        for m in m_values:
            output[f'E50ref_m_{str(m).replace(".","_")}'] = np.nan
            output[f'COV_E50_ref_m_{str(m).replace(".","_")}'] = np.nan
        output.update({'chosen_m': np.nan, 'chosen_COV (%)': np.nan, 'chosen_E50ref (kPa)': np.nan})
    return pd.Series(output)
# %%
# ==============================================================================
# 3. EXTRACTION CONFIG & MAIN EXECUTION
# ==============================================================================


# --- Updated Features Dictionary (Header, Sub-header, Label) ---
features_to_extract = {
    "sample_type": [
        ("GENERAL", None, "Type of sample:"),
        ("GENERAL", None, "Type of sample")
        # ("Initial Sample Conditions", "Type of sample"),
        # ("Initial Specimen Conditions", "Sample type"),
        # ("Test identification", "Specimen condition")
    ],
    "bulk_density (Mg/m3)": [
        ("INITIAL", None, "Bulk density"),
        ("INITIAL CONDITIONS", None, "Bulk density"),
        ("Initial Sample Conditions", None, "Bulk density"),
        ("Initial Specimen Conditions", None, "Bulk density"),
    ],
    "dry_density (Mg/m3)": [
        ("INITIAL", None, "Dry density"),
        ("INITIAL CONDITIONS", None, "Dry density"),
        ("Initial Sample Conditions", None, "Dry density"),
        ("Initial Specimen Conditions", None, "Dry density"),
    ],
    "e0 (-)": [
        ("INITIAL", None, "Void ratio"),
        ("INITIAL CONDITIONS", None, "Void ratio"),
        ("Initial Sample Conditions", None, "Void ratio"),
        ("Initial Sample Conditions", None, "Initial Void ratio"),
        ("Initial Specimen Conditions", None, "Void ratio"),
        ("Initial Specimen Conditions", None, "Initial void ratio")
    ],
    "water_content (%)": [
        ("INITIAL", None, "Water content"),
        ("INITIAL CONDITIONS", None, "Water content"),
        ("Initial Sample Conditions", None, "Water content"),
        ("Initial Specimen Conditions", None, "Water content")
    ],
    "interface_roughness (μm)": [
        ("GENERAL", None, "Interface Roughness") 
    ],
    "phi (degree)": [
        ("SHEAR STRENGTH PARAMETERS", None, "Effective angle of internal friction (φ')"),
        ("MOHR FAILURE ENVELOPE", None, "Effective angle of internal friction (φ')"),
        ("MOHR FAILURE ENVELOPE", None, "Effective angle of internal friction (j')")
    ],
    "phi_slow_shear_peak (degree)": [
        ("Slow Shear - At peak stress", None, "Shear angle")
    ],
    "phi_slow_shear_residual (degree)": [
        ("Slow Shear - At residual stress", None, "Shear angle")
    ],
    "phi_3spec (degree)": [
        ("Mohr Failure Envelope for all three specimens", None, "Effective angle of internal friction (j')"),
        ("Mohr Failure Envelope for all three specimens", None, "Effective angle of internal friction (φ')")
    ],
    "cohesion (kPa)": [
        ("SHEAR STRENGTH PARAMETERS", None, "Effective cohesion (c')"),
        ("MOHR FAILURE ENVELOPE", None, "Effective cohesion (c')")
    ],
    "cohesion_3spec (kPa)": [
        ("Mohr Failure Envelope for all three specimens", None, "Effective cohesion (c')")
    ],
    "undrained_shear_strength (kPa)": [
        ("FAILURE", None, "Undrained shear strength"),
        ("SHEARING STAGE", "At peak deviator stress", "Undrained shear strength"),
        ("Shearing Stage - At peak deviator stress (within 10% axial strain)", None, "Undrained shear strength")
    ],
    "torvane (kPa)": [
        ("INITIAL", None, "Torvane"),
        ("INITIAL CONDITIONS", None, "Torvane"), 
        ("Initial Specimen Conditions", None, "Torvane"),
        ("Initial Sample Conditions", None, "Torvane")
    ],
    "pocket_penetrometer (kPa)": [
        ("INITIAL", None, "Pocket penetrometer")
    ],
    "secant_modulus_e50_sigma_eff_3 (kPa)": [
        ("SHEARING STAGE", None, "Initial effective cell pressure"),
        ("SHEARING STAGE", None, "Initial effective radial pressure"),
        ("SHEAR STAGE (DRAINED)", None, "Initial effective radial pressure")
    ],
    #"secant_modulus_e50_u_0 (kPa)": [ # This doesnt work TODO
        #("SHEARING STAGE", None, "Initial effective pore pressure")
    #],
    "secant_modulus_e50_deviator_stress_peak_qf (kPa)": [
        ("SHEARING STAGE", "At peak deviator stress", "Corrected deviator stress"),
        ("SHEAR STAGE (DRAINED)", "At peak deviator stress", "Corrected deviator stress")
    ],
    "secant_modulus_e50 (kPa)": [
        ("SHEARING STAGE", "At peak deviator stress", "Secant modulus (E50) at e50"), 
        ("SHEARING STAGE", "At peak deviator stress", "Secant modulus (E50)"),
        ("SHEARING STAGE", "At peak deviator stress", "Secant modulus (E50) at e 50"),
        ("Shearing Stage - At peak deviator stress (within 10% axial strain", None, "Secant modulus [E50] at e50"),
        ("SHEAR STAGE (DRAINED)", "At peak deviator stress", "Secant modulus (E50) at ɛ50")
    ],
    "borehole": [
        ("TEST IDENTIFICATION", None, "Borehole:"),
        ("TEST IDENTIFICATION", None, "Borehole"),
        ("Test Identification", None, "Location"),
        ("TEST IDENTIFICATION", None, "Borehole :")
    ],
    "depth": [
        ("TEST IDENTIFICATION", None, "Depth:"),
        ("TEST IDENTIFICATION", None, "Depth"),
        ("TEST IDENTIFICATION", None, "Depth :")
    ]
}
# %%
import os as _owc_os
from pathlib import Path as _OwcPath
_OWC_ROOT = _OwcPath(_owc_os.environ["OWC_DATA_ROOT"])  # injected by pipeline.a_process
parent_directory = _OWC_ROOT / "02_lab_data_raw" / "TNW"
all_data = []

# --- Loop Files ---
for file_path in parent_directory.rglob("*.xlsx"):
    try: df = pd.read_excel(file_path, header=None)
    except: continue
    
    spec_cols = get_specimen_columns(df)
    file_spec_data = {c: {"source_file": file_path.name, "specimen_id": l, "borehole": None, "depth": None} for c, l in spec_cols.items()}
    
    cur_sec, cur_sub = None, None
    for _, row in df.iterrows():
        f_cell = str(row[0]).strip() if pd.notna(row[0]) else ""
        if not f_cell: continue
        if f_cell.isupper() and len(f_cell.split()) < 5: cur_sec, cur_sub = f_cell.lower(), None
        elif pd.isna(row[1]) and not f_cell.isupper(): cur_sub = f_cell.lower()
        
        if "borehole" in f_cell.lower(): 
            v = clean_value(row[1])
            for r in file_spec_data.values(): r["borehole"] = v
        if "depth" in f_cell.lower() and "initial" not in f_cell.lower(): 
            v = clean_value(row[1])
            for r in file_spec_data.values(): r["depth"] = v

        for feat, aliases in features_to_extract.items():
            for sec, sub, label in aliases:
                if cur_sec == (sec.lower() if sec else None) and cur_sub == (sub.lower() if sub else None):
                    if f_cell.lower().replace(":","").strip() == label.lower().replace(":","").strip():
                        for c_idx in spec_cols.keys():
                            if c_idx < len(row) and pd.notna(row[c_idx]) and "[" not in str(row[c_idx]):
                                file_spec_data[c_idx][feat] = row[c_idx]

    for idx, rec in file_spec_data.items():
        ctx = f"{rec.get('sample_type','')} {rec.get('specimen_id','')}".lower()
        if "undisturbed" in ctx: rec["sample_type"] = "Undisturbed"
        elif "remoulded" in ctx: rec["sample_type"] = "Remoulded"
        elif "re-compacted" in ctx or "recompacted" in ctx: rec["sample_type"] = "Re-compacted"

    all_data.extend(file_spec_data.values())
# %%
# --- Final Processing ---
master_df = pd.DataFrame(all_data)
master_df = normalize_depth_column(master_df)
master_df["test_type"] = master_df["source_file"].str.split("_").str[5:].str.join("_").str.replace(r"_XLSX_V\d+_F.xlsx", "", regex=True).str.replace(r"\d+", "", regex=True).str.upper()
master_df["test_type"] = master_df.apply(identify_extension_tests, axis=1).apply(clean_test_type)

final_df = aggregate_specimens(master_df, "borehole", "depth")

# Apply Analytic Functions
final_df = pd.concat([final_df, final_df.apply(split_shear_parameters_robust, axis=1)], axis=1)
final_df = pd.concat([final_df, final_df.apply(extract_su_dimensions, axis=1)], axis=1)

avg_cols = ['water_content (%)', 'bulk_density (Mg/m3)', 'dry_density (Mg/m3)', 'e0 (-)', 
            'torvane (kPa)', 'pocket_penetrometer (kPa)']

for col in avg_cols:
    if col in final_df.columns:
        final_df[col] = (
            final_df[col]
                .apply(clean_numeric_list)
                .apply(safe_average_with_scatter_control)
        )

final_df = pd.concat([final_df, final_df.apply(optimize_m_parameter, axis=1)], axis=1)

# %% Final touches
export_df = final_df[['borehole', 'depth', 'test_type', 'source_file', 'water_content (%)', 'bulk_density (Mg/m3)',
       'dry_density (Mg/m3)', 'e0 (-)', 'torvane (kPa)',
       'pocket_penetrometer (kPa)', 'phi_CD (degree)', 'cohesion_CD (kPa)',
       'phi_SB (degree)', 'cohesion_SB (kPa)', 'su_UU_undisturbed (kPa)',
       'su_UU_remoulded (kPa)', 'su_CU_undisturbed (kPa)',
       'su_CU_remoulded (kPa)', 'su_CUe_undisturbed (kPa)',
       'secant_modulus_e50_sigma_eff_3 (kPa)', 'secant_modulus_e50 (kPa)', 'chosen_E50ref (kPa)', 'chosen_m']].copy()

# # Convert kPa → MPa
# export_df["E50ref (MPa)"] = export_df["chosen_E50ref (kPa)"].astype(float) / 1000.0

# # Convert Mg/m³ → kN/m³
# export_df["gamma (kN/m3)"] = export_df["bulk_density (Mg/m3)"].astype(float) * 9.81
# export_df["gamma_d (kN/m3)"] = export_df["dry_density (Mg/m3)"].astype(float) * 9.81

# # Drop old columns
# export_df.drop(columns=["bulk_density (Mg/m3)", "dry_density (Mg/m3)", "chosen_E50ref (kPa)"], inplace=True)
# export_df.rename(columns={
#     "chosen_m": "E50ref_m_parameter (-)"}, inplace=True)
# export_df

# print("Processing Complete. Final Shape:", final_df.shape)

# output_file = _OWC_ROOT / "03_lab_data_cleaned" / "TNW_soil_parameters.csv"
# # export_df.to_csv(output_file, index=False, encoding="utf-8")

# print(f"✅ Extraction completed. Results saved to {output_file}")

def to_mpa(x):
    """Convert a scalar or list of kPa values to MPa, preserving structure."""
    if isinstance(x, list):
        return [v / 1000.0 for v in x if pd.notna(v)]
    if pd.isna(x):
        return x
    return x / 1000.0

# Convert kPa -> MPa
export_df["E50ref (MPa)"] = pd.to_numeric(export_df["chosen_E50ref (kPa)"], errors='coerce') / 1000.0
export_df["E50 (MPa)"] = export_df["secant_modulus_e50 (kPa)"].apply(to_mpa)

# sigma3' stays in kPa 
export_df.rename(columns={
    "secant_modulus_e50_sigma_eff_3 (kPa)": "E50_sigma3_eff (kPa)"
}, inplace=True)

# Convert Mg/m3 -> kN/m3
export_df["gamma (kN/m3)"] = pd.to_numeric(export_df["bulk_density (Mg/m3)"], errors='coerce') * 9.81
export_df["gamma_d (kN/m3)"] = pd.to_numeric(export_df["dry_density (Mg/m3)"], errors='coerce') * 9.81

# Drop old columns
export_df.drop(columns=[
    "bulk_density (Mg/m3)",
    "dry_density (Mg/m3)",
    "secant_modulus_e50 (kPa)",
    "chosen_E50ref (kPa)"
], inplace=True)

export_df.rename(columns={"chosen_m": "E50ref_m_parameter (-)"}, inplace=True)

print("✅ PIPELINE COMPLETE")
print("Final shape:", export_df.shape)
export_df

# %%
output_file = _OWC_ROOT / "03_lab_data_cleaned" / "TNW_soil_parameters.csv"
print(f"✅ Extraction completed. Results saved to {output_file}")
export_df.to_csv(output_file, index=False, encoding="utf-8")



# %%
