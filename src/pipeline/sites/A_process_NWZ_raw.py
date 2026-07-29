# ============================================================
#  Geotechnical Laboratory Data Processing Pipeline
# ============================================================
"""
Scrapes Nederwiek lab test .xlsx files (one file per test) into a single
tidy dataset, keyed by borehole + depth.

Pipeline stages:
1. Scrape each .xlsx into per-specimen records (source_file, borehole, depth,
   sample_type, and lab parameters via features_to_extract aliases).
2. Assemble into master_df; clean borehole names, parse depth, derive test_type
   from filename.
3. Aggregate specimens sharing the same borehole+depth into list-valued rows
   (multiple tests/specimens per depth).
4. Derive combined phi/cohesion (CD, RS), su components (UU/CU/CUe), and
   E50ref via Janbu power-law m-optimization.
5. Export cleaned, unit-converted CSV (gamma in kN/m3, E50 in MPa, etc.).
"""

# %%
# -----------------------------
# Imports
# -----------------------------
import pandas as pd
import numpy as np
import re
from pathlib import Path

#%%
# ============================================================
#  Utility Functions
# ============================================================

def normalize_depth_column(df, depth_col="depth"):
    """
    Convert depth intervals like '42.25 - 42.75' into numeric averages.
    Leaves single numeric depths unchanged.
    Non-numeric or missing values become NaN.
    """
    def parse_depth(val):
        if pd.isna(val):
            return np.nan
        s = str(val).strip()
        # Match intervals like "42.25 - 42.75"
        if re.match(r"^\s*\d+(\.\d+)?\s*-\s*\d+(\.\d+)?\s*$", s):
            parts = re.split(r"-", s)
            try:
                nums = [float(p) for p in parts]
                return sum(nums) / len(nums)
            except Exception:
                return np.nan
        # Try plain numeric
        try:
            return float(s)
        except Exception:
            return np.nan

    df[depth_col] = df[depth_col].apply(parse_depth)
    return df


def clean_test_type(test_str):
    if pd.isna(test_str):
        return test_str
    
    # Convert to string and uppercase for easier matching
    s = str(test_str).upper()

    # Define the mapping rules (Order matters: more specific first)
    if 'CAUCBE' in s: return 'CU + BE'
    if 'CAUE' in s or 'CIUE' in s: return 'CUe'
    if 'CAU' in s or 'CIU' in s: return 'CU'
    if 'CID' in s: return 'CD'
    if 'RS-' in s or 'RS_RS' in s or 'ISO' in s or 'ICPR' in s or 'ICRS' in s: return 'RS'
    if 'DSS' in s: return 'DSS'
    if 'CRS' in s: return 'CRS'
    if 'RC' in s: return 'RC'
    if 'UU' in s: return 'UU'
    if 'OED' in s: return 'OED'
    if 'PERM' in s or 'TXP' in s or 'CHP' in s: return 'PERM'
    if 'SB' in s: return 'SB'
        
    return test_str # Return original if no match


# Version 1
# def aggregate_specimens(df, borehole_col, depth_col):
#     """
#     Groups dataframe by borehole and depth.
#     If multiple specimens exist, values are collected into lists.
#     Keeps borehole and depth columns intact and robustly handles mixed types.
#     """
#     # Keep the group keys separate
#     grouped_keys = df[[borehole_col, depth_col]].drop_duplicates()

#     # Columns to aggregate
#     cols_to_agg = [c for c in df.columns if c not in [borehole_col, depth_col]]

#     def agg_func(series):
#         # Remove NaNs
#         series = [x for x in series if pd.notna(x)]
#         if not series:
#             return np.nan
#         if len(series) == 1:
#             return series[0]
#         return series  # keep as list if multiple values

#     # Aggregate the remaining columns
#     aggregated = df.groupby([borehole_col, depth_col], dropna=False)[cols_to_agg].agg(agg_func).reset_index(drop=True)

#     # Merge the keys back
#     final_df = pd.concat([grouped_keys.reset_index(drop=True), aggregated], axis=1)

#     return final_df

# Version 2
# def aggregate_specimens(df, borehole_col, depth_col):
#     cols_to_agg = [c for c in df.columns if c not in [borehole_col, depth_col]]

#     def agg_func(series):
#         series = [x for x in series if pd.notna(x)]
#         if not series:
#             return np.nan
#         if len(series) == 1:
#             return series[0]
#         return series

#     aggregated = (
#         df.groupby([borehole_col, depth_col], dropna=False)[cols_to_agg]
#         .agg(agg_func)
#         .reset_index()  # <-- keeps borehole/depth correctly attached to their own group
#     )
#     return aggregated

# Version 3
# def aggregate_specimens(df, borehole_col, depth_col):
#     cols_to_agg = [c for c in df.columns if c not in [borehole_col, depth_col]]

#     def agg_func(series):
#         vals = list(series)
#         if len(vals) == 1:
#             return vals[0]
#         return vals  # keep NaNs as placeholders -- preserves positional alignment across columns

#     aggregated = (
#         df.groupby([borehole_col, depth_col], dropna=False)[cols_to_agg]
#         .agg(agg_func)
#         .reset_index()
#     )
#     return aggregated

# Version 4
def aggregate_specimens(df, borehole_col, depth_col):
    # v4: groups specimens by borehole+depth into lists; keeps NaNs as placeholders
    # so all columns stay index-aligned with test_type. Also re-pairs E50/sigma3
    # so a value only survives if BOTH were measured together (drops orphaned NaN pairs).
    cols_to_agg = [c for c in df.columns if c not in [borehole_col, depth_col]]
    e50_col = 'secant_modulus_e50 (kPa)'
    s3_col = 'secant_modulus_e50_sigma_eff_3 (kPa)'

    def agg_func(sub_df):
        result = {col: (list(sub_df[col]) if len(sub_df) > 1 else sub_df[col].iloc[0]) for col in cols_to_agg}

        if e50_col in result and s3_col in result:
            e50 = result[e50_col] if isinstance(result[e50_col], list) else [result[e50_col]]
            s3 = result[s3_col] if isinstance(result[s3_col], list) else [result[s3_col]]
            if len(e50) == len(s3):
                paired = [(e, s) for e, s in zip(e50, s3) if pd.notna(e) and pd.notna(s)]
                e_new, s_new = zip(*paired) if paired else ([np.nan], [np.nan])
                result[e50_col] = e_new[0] if len(e_new) == 1 else list(e_new)
                result[s3_col] = s_new[0] if len(s_new) == 1 else list(s_new)

        return pd.Series(result)

    return df.groupby([borehole_col, depth_col], dropna=False).apply(agg_func).reset_index()


def safe_average_with_scatter_control(val):
    # 1. Standardize input to a list of valid numbers
    def clean_to_floats(items):
        clean_list = []
        # Ensure we are iterating over a list/array
        iterable = items if isinstance(items, (list, np.ndarray, pd.Series)) else [items]
        
        for x in iterable:
            try:
                # Strip strings and handle ' ' or 'None'
                if isinstance(x, str):
                    x = x.strip()
                    if x == "": continue
                
                f_val = float(x)
                if pd.notna(f_val):
                    clean_list.append(f_val)
            except (ValueError, TypeError):
                # Skip anything that isn't a number (like ' ', 'N/A', or text)
                continue
        return clean_list

    data = clean_to_floats(val)

    if not data:
        return np.nan
    
    if len(data) == 1:
        return data[0]

    # 2. Statistical Control
    data_min = min(data)
    data_max = max(data)
    data_mean = sum(data) / len(data)

    if data_mean == 0:
        return 0.0

    # (Max - Min) / Mean > 10%
    scatter = (data_max - data_min) / data_mean
    
    if scatter > 0.10:
        return np.nan 
    
    return data_mean

def simplify_geotechnical_data_phi_cohesion(df):
    """Process phi and cohesion columns for CD and RS tests. (Nederwiek dataset)"""
    # 1. Helper to extract the first valid number from a list or scalar
    def get_first_val(x):
        if isinstance(x, list):
            # Filter out NaNs and take the first item
            valid = [v for v in x if pd.notna(v)]
            return valid[0] if valid else np.nan
        return x

    # 2. Helper for RS Tests (Peak and Residual)
    def extract_rs_params(row):
        # We look for the RS values specifically in the designated RS columns
        peak = get_first_val(row.get('phi_slow_shear_peak (degree)', np.nan))
        residual = get_first_val(row.get('phi_slow_shear_residual (degree)', np.nan))
        return pd.Series([peak, residual])

    # 3. Process CD Test Phis (phi and phi_3spec)
    # We take the first valid value from either column
    df['phi_CD (degree)'] = df['phi_3spec (degree)'].apply(get_first_val)
    # Fallback: if phi_final is still NaN, try the standard 'phi' column
    df['phi_CD (degree)'] = df['phi_CD (degree)'].fillna(df['phi (degree)'].apply(get_first_val))

    # 4. Process CD Test Cohesion
    df['cohesion_CD (kPa)'] = df['cohesion_3spec (kPa)'].apply(get_first_val)
    df['cohesion_CD (kPa)'] = df['cohesion_CD (kPa)'].fillna(df['cohesion (kPa)'].apply(get_first_val))

    # 5. Extract Ring Shear specific columns
    df[['phi_RS_peak (degree)', 'phi_RS_residual (degree)']] = df.apply(extract_rs_params, axis=1)

    # 6. Final Cleanup: Select only the "Clean" columns for your final report
    important_cols = [
        'borehole', 'depth', 'test_type', 'sample_type', 
        'phi_CD (degree)', 'cohesion_CD (kPa)', 'phi_RS_peak (degree)', 'phi_RS_residual (degree)',
        'secant_modulus_e50_sigma_eff_3 (kPa)', 'secant_modulus_e50 (kPa)', 
        'secant_modulus_e50_deviator_stress_peak_qf (kPa)',
        'undrained_shear_strength (kPa)',
        'water_content (%)', 'bulk_density (Mg/m3)', 'dry_density (Mg/m3)', 
        'e0 (-)', 'torvane (kPa)', 'pocket_penetrometer (kPa)', 'source_file' # Add others as needed
    ]
    
    # Ensure columns exist before selecting
    existing_cols = [c for c in important_cols if c in df.columns]
    
    return df[existing_cols]

def extract_su_dimensions(row):
    """
    Break down of undrained shear strength (su) into UU, CU, CUe components.
    Handles both undisturbed and remoulded samples.
    1. UU Tests:
        - su_UU_undisturbed (kPa)
        - su_UU_remoulded (kPa)
    2. CU Tests:
        - su_CU_undisturbed (kPa)
        - su_CU_remoulded (kPa)
    3. CUe Tests:
        - su_CUe_undisturbed (kPa)
    """
    res = {
        'su_UU_undisturbed (kPa)': np.nan, 'su_UU_remoulded (kPa)': np.nan,
        'su_CU_undisturbed (kPa)': np.nan, 'su_CU_remoulded (kPa)': np.nan,
        'su_CUe_undisturbed (kPa)': np.nan
    }

    def to_flat_list(val):
        if isinstance(val, (list, np.ndarray)):
            flat = []
            for item in val:
                if isinstance(item, (list, np.ndarray)): flat.extend(item)
                else: flat.append(item)
            return flat
        return [val]

    # Normalize to Upper to catch CUe, cue, CUE
    tests = [str(x).upper().strip() for x in to_flat_list(row.get('test_type', []))]
    samples = [str(x).lower().strip() for x in to_flat_list(row.get('sample_type', []))]
    
    # CRITICAL: Dynamically find the qf column in case the name has extra spaces
    qf_col = [c for c in row.index if 'deviator_stress_peak_qf' in c]
    qf_vals = to_flat_list(row.get(qf_col[0], [])) if qf_col else []
    
    uu_col = [c for c in row.index if 'undrained_shear_strength' in c]
    uu_vals = to_flat_list(row.get(uu_col[0], [])) if uu_col else []

    for i in range(len(tests)):
        t = tests[i]
        s = samples[i] if i < len(samples) else ""
        
        # Determine the value (su = qf/2)
        qf = qf_vals[i] if i < len(qf_vals) else np.nan
        su_from_qf = float(qf) / 2.0 if pd.notna(qf) else np.nan
        
        # --- UU Logic ---
        if "UU" in t:
            direct_su = uu_vals[i] if i < len(uu_vals) else np.nan
            val = direct_su if pd.notna(direct_su) and direct_su != 0 else su_from_qf
            
            if pd.notna(val):
                if "remoulded" in s: res['su_UU_remoulded (kPa)'] = val
                else: res['su_UU_undisturbed (kPa)'] = val

        # --- CU / CAUC Logic ---
        # Added 'CUE' check here to handle 'CUe' normalized to 'CUE'
        elif any(k in t for k in ["CU", "CAUC"]):
            if "CUE" in t: # Specific check for CUe
                if pd.notna(su_from_qf):
                    res['su_CUe_undisturbed (kPa)'] = su_from_qf
            else: # Standard CU
                if pd.notna(su_from_qf):
                    if "remoulded" in s: res['su_CU_remoulded (kPa)'] = su_from_qf
                    else: res['su_CU_undisturbed (kPa)'] = su_from_qf

    return pd.Series(res)

# Row-level only: wipes whole E50 list if NO test in the row is CD. 
# Doesn't filter individual list entries.
def filter_e50_by_test_type(row):
    """
    Wipes the 'secant_modulus_e50 (kPa)' value if the test type is not 'CD'.
    """
    # Specify the target column name
    target_col = 'secant_modulus_e50 (kPa)'
    
    # Identify test types for this row
    test_val = row.get('test_type', [])
    
    # Check if "CD" is present in the test list or string
    if isinstance(test_val, (list, np.ndarray)):
        is_cd = any("CD" in str(t).upper() for t in test_val)
    else:
        is_cd = "CD" in str(test_val).upper()

    # If the test is not CD, wipe the E50 value
    if not is_cd and target_col in row.index:
        row[target_col] = np.nan
            
    return row

# Assumes test_type, E50, sigma3 lists are same length/order 
# (guaranteed by aggregate_specimens v4)
def optimize_m_parameter(row):
    """
    This function calculates E50ref values for m = 0.5, 0.75, and 1.0
    using the Janbu power law normalization. It computes the Coefficient of Variation (COV)
    for each m and selects the optimal m based on the lowest COV under 20%.
    
    Lets assume the following columns exist in the row:
    - 'test_type': CD only
    - 'secant_modulus_e50 (kPa)': List of measured E50 values
    - 'secant_modulus_e50_sigma_eff_3 (kPa)': List of effective confining stresses (σ'3)
    - 'phi_CD': Friction angle for CD tests
    - 'cohesion_CD': Cohesion for CD tests
    Returns a Series with:
    - 'chosen_m': Optimal m value
    - 'chosen_COV (%)': Corresponding COV
    - 'chosen_E50ref (kPa)': Corresponding E50ref (for pref=100 kPa)
    """
    p_ref = 100.0
    m_values = [0.5, 0.75, 1.0]
    output = {}

    # --- 1. Helper to ensure iterables ---
    def to_list(val):
        if isinstance(val, (list, np.ndarray, pd.Series)):
            return [x for x in val]
        elif pd.isna(val) or val is None:
            return []
        else:
            return [val]

    # --- 2. Extract and flatten row values ---
    test_types = to_list(row.get('test_type', []))
    e50_list = to_list(row.get('secant_modulus_e50 (kPa)', []))
    s3_list = to_list(row.get('secant_modulus_e50_sigma_eff_3 (kPa)', []))

    # --- 3. Filter CD / CID indices safely ---
    cd_indices = [i for i, t in enumerate(test_types) if str(t).upper() in ['CD', 'CID']]

    # --- 4. Align e50 and s3 values with test_types, skip NaNs ---
    e50_measured = np.array([float(e50_list[i]) for i in cd_indices if i < len(e50_list) and pd.notna(e50_list[i])])
    s3_eff = np.array([float(s3_list[i]) for i in cd_indices if i < len(s3_list) and pd.notna(s3_list[i])])

    # Get phi and cohesion for 'a' calculation (Attraction)
    phi = float(row.get('phi_CD', 0))
    coh = float(row.get('cohesion_CD', 0))
    a = coh / np.tan(np.radians(phi)) if phi > 0 else 0

    # 3. Calculation Logic
    # We need matching lengths and ideally > 1 point for a meaningful COV
    if len(e50_measured) > 0 and len(e50_measured) == len(s3_eff):
        cov_results = {}
        e50_ref_means = {}

        for m in m_values:
            m_str = str(m).replace('.', '_')
            
            # Normalization formula: Janbu Power Law
            e50_ref_set = e50_measured / ((s3_eff + a) / (p_ref + a))**m
            
            mean_val = np.mean(e50_ref_set)
            std_val = np.std(e50_ref_set)
            
            # If only 1 point, std is 0, so COV is 0. 
            cov = (std_val / mean_val * 100) if mean_val != 0 else np.nan
            
            output[f'E50ref_m_{m_str}'] = mean_val
            output[f'COV_E50_ref_m_{m_str}'] = cov
            
            cov_results[m] = cov
            e50_ref_means[m] = mean_val

        # 4. Selection Logic
        best_m = np.nan
        final_cov = np.nan
        final_e50ref = np.nan

        # CRITERIA:
        # 1. Must have more than 1 CD specimen to trust the COV optimization
        # 2. COV must be < 20%
        # 3. Minimum COV among the m-values
        if len(e50_measured) > 1:
            valid_m = {m: cov for m, cov in cov_results.items() if pd.notna(cov) and cov < 20}
            if valid_m:
                best_m = min(valid_m, key=valid_m.get)
                final_cov = valid_m[best_m]
                final_e50ref = e50_ref_means[best_m]
        else:
            # If only one CD test exists, we can't "optimize". 
            # We pick a default m (e.g. 0.5 for sand) or leave as NaN.
            # Let's leave as NaN to maintain strict QC for your thesis.
            pass
        
        output['chosen_m'] = best_m
        output['chosen_COV (%)'] = final_cov
        output['chosen_E50ref (kPa)'] = final_e50ref
        
    else:
        # Fill NaNs for rows with no CD data
        cols = ['chosen_m', 'chosen_COV (%)', 'chosen_E50ref (kPa)']
        for m in m_values:
            m_str = str(m).replace('.', '_')
            cols.extend([f'E50ref_m_{m_str}', f'COV_E50_ref_m_{m_str}'])
        for c in cols: output[c] = np.nan

    return pd.Series(output)


# %% Features to extract mapping

features_to_extract = {
    "sample_type": [
        ("Initial Specimen Conditions", "Type of sample"),
        ("Initial Sample Conditions", "Type of sample"),
        ("Initial Specimen Conditions", "Sample type"),
        ("Test identification", "Specimen condition")
    ],
    "bulk_density (Mg/m3)": [
        ("INITIAL", "Bulk density"),
        ("INITIAL CONDITIONS", "Bulk density"),
        ("Initial Sample Conditions", "Bulk density"),
        ("Initial Specimen Conditions", "Bulk density"),
    ],
    "dry_density (Mg/m3)": [
        ("INITIAL", "Dry density"),
        ("INITIAL CONDITIONS", "Dry density"),
        ("Initial Sample Conditions", "Dry density"),
        ("Initial Specimen Conditions", "Dry density"),
    ],
    "e0 (-)": [
        ("INITIAL", "Void ratio"),
        ("INITIAL CONDITIONS", "Void ratio"),
        ("Initial Sample Conditions", "Void ratio"),
        ("Initial Sample Conditions", "Initial Void ratio"),
        ("Initial Specimen Conditions", "Void ratio"),
        ("Initial Specimen Conditions", "Initial void ratio")
    ],
    "water_content (%)": [
        ("INITIAL", "Water content"),
        ("INITIAL CONDITIONS", "Water content"),
        ("Initial Sample Conditions", "Water content"),
        ("Initial Specimen Conditions", "Water content"), 
        ("Initial Specimen Conditions", "Water content ")
    ],
    "interface_roughness (μm)": [
        ("GENERAL", "Interface Roughness") 
    ],
    "phi (degree)": [
        ("SHEAR STRENGTH PARAMETERS", "Effective angle of internal friction (φ')"),
        ("MOHR FAILURE ENVELOPE", "Effective angle of internal friction (φ')"),
        ("MOHR FAILURE ENVELOPE", "Effective angle of internal friction (j')"),
        ("Mohr Failure Envelope", "Effective angle of internal friction (φ')")
    ],
    "phi_slow_shear_peak (degree)": [
        ("Slow Shear - At peak stress", "Shear angle")
    ],
    "phi_slow_shear_residual (degree)": [
        ("Slow Shear - At residual stress", "Shear angle")
    ],
    "phi_3spec (degree)": [
        ("Mohr Failure Envelope for all three specimens", "Effective angle of internal friction (j')"),
        ("Mohr Failure Envelope for all three specimens", "Effective angle of internal friction (φ')")
    ],
    "cohesion (kPa)": [
        ("SHEAR STRENGTH PARAMETERS", "Effective cohesion (c')"),
        ("MOHR FAILURE ENVELOPE", "Effective cohesion (c')"),
        ("Mohr Failure Envelope", "Effective cohesion (c')")
    ],
    "cohesion_3spec (kPa)": [
        ("Mohr Failure Envelope for all three specimens", "Effective cohesion (c')")
    ],
    "undrained_shear_strength (kPa)": [
        ("FAILURE", "Undrained shear strength"),
        ("Shearing Stage - At peak deviator stress (within 10% axial strain)" , "Undrained shear strength")
    ],
    "torvane (kPa)": [
        ("INITIAL", "Torvane"),
        ("INITIAL", "Torvane 90°"),
        ("INITIAL CONDITIONS", "Torvane"), 
        ("INITIAL CONDITIONS", "Torvane 90°"),
        ("Initial Specimen Conditions", "Torvane"),
        ("Initial Specimen Conditions", "Torvane°"),
        ("Initial Sample Conditions", "Torvane"),
        ("Initial Sample Conditions", "Torvane°")
    ],
    "pocket_penetrometer (kPa)": [
        ("INITIAL", "Pocket penetrometer"),
        ("INITIAL", "Pocket penetrometer 90°"),
        ("INITIAL CONDITIONS", "Pocket penetrometer"),
        ("INITIAL CONDITIONS", "Pocket penetrometer 90°"),
        ("Initial Specimen Conditions", "Pocket penetrometer"),
        ("Initial Specimen Conditions", "Pocket penetrometer°"),
        ("Initial Sample Conditions", "Pocket penetrometer"),
        ("Initial Sample Conditions", "Pocket penetrometer°")
    ],
    "secant_modulus_e50_radial_ref (kPa)": [
        ("Shearing Stage", "Initial effective radial pressure"),
        ("Shearing", "Initial effective cell pressure")
    ],
    "secant_modulus_e50_axial_ref (kPa)": [
        ("Shearing Stage", "Initial effective axial pressure")
    ],

    #-------------
    "secant_modulus_e50_sigma_eff_3 (kPa)": [
        ("SHEARING STAGE", "Initial effective cell pressure"),
        ("SHEARING STAGE", "Initial effective radial pressure"),
        ("SHEAR STAGE (DRAINED)", "Initial effective radial pressure"),
        ("Shearing", "Initial effective cell pressure")
    ],
    "secant_modulus_e50_u_0 (kPa)": [ 
        ("SHEARING STAGE", "Initial pore pressure"),
        ("SHEARING", "Initial pore pressure")
    ],
    "secant_modulus_e50_deviator_stress_peak_qf (kPa)": [
        ("SHEARING STAGE - At peak deviator stress", "Corrected deviator stress"),
        ("SHEAR STAGE (DRAINED) - At peak deviator stress", "Corrected deviator stress"),
        ("Shearing - At peak deviator stress", "Corrected deviator stress")
    ],
    #-------------
    "secant_modulus_e50 (kPa)": [
        ("SHEARING STAGE", "Secant modulus (E50) at e50"),
        ("SHEARING STAGE", "Secant modulus (E50) at e 50"),
        ("SHEARING STAGE", "Secant modulus (E50)"),
        ("Shearing stage - At peak deviator stress", "Secant modulus (E50) at e50"),
        ("Shearing stage - At peak deviator stress", "Secant modulus (E50) at e 50"),
        ("Shearing stage - At peak deviator stress", "Secant modulus (E50)"),
        ("Shearing Stage - At peak deviator stress (within 10% axial strain", "Secant modulus [E50] at e50"),
        ("Shearing - At peak deviator stress", "Secant modulus (E50) at e50")
    ],
    "borehole": [
        ("TEST IDENTIFICATION", "Borehole:"),
        ("TEST IDENTIFICATION", "Borehole"),
        ("TEST IDENTIFICATION", "Borehole :"),
        ("Test Identification", "Location"),
        ("Test identification", "Location")
    ],
    "depth": [
        ("TEST IDENTIFICATION", "Depth:"),
        ("TEST IDENTIFICATION", "Depth"),
        ("TEST IDENTIFICATION", "Depth :")
    ],
    # Extend with shear_angle, secant_modulus_e50, etc. if needed
}


# %% ###################################
# Path
# ============================================================
#  SCRAPING STAGE (YOUR SCRIPT – INTEGRATED)
# ============================================================
import os as _owc_os
from pathlib import Path as _OwcPath
_OWC_ROOT = _OwcPath(_owc_os.environ["OWC_DATA_ROOT"])  # injected by pipeline.a_process
parent_directory = _OWC_ROOT / "02_lab_data_raw" / "NWZ"



# %% 
# Main Processing Loop
all_data = []

# REQUIRED: feature alias dictionary
# features_to_extract = { "canonical_name": [(section, label), ...] }

for file_path in parent_directory.rglob("*.xlsx"):
    try:
        df = pd.read_excel(file_path, header=None)
    except Exception as e:
        print(f"❌ Read Error: {file_path.name} | {e}")
        continue

    header_sample = df.iloc[:10].fillna("").astype(str)
    spec_col_indices = []
    spec_headers = []

    for col_idx in range(2, df.shape[1]):
        col_text_combined = " ".join(header_sample[col_idx].tolist()).lower()
        if any(k in col_text_combined for k in ["specimen", "sample", "remoulded", "undisturbed"]) or \
           any(re.search(r'\d', str(cell)) for cell in header_sample[col_idx] if pd.notna(cell)):

            spec_col_indices.append(col_idx)
            name_cell = f"Specimen {len(spec_col_indices)}"
            for cell in header_sample[col_idx]:
                c_str = str(cell).strip()
                if any(k in c_str.lower() for k in ["specimen", "sample", "undisturbed", "remoulded", "re-compacted"]):
                    name_cell = c_str
                    break
            spec_headers.append(name_cell)

    if not spec_col_indices:
        spec_col_indices = [2]
        spec_headers = ["Specimen 1"]

    file_records = {
        idx: {
            "source_file": file_path.name,
            "specimen_id": spec_headers[i],
            "sample_type": None,
            "borehole": None
        }
        for i, idx in enumerate(spec_col_indices)
    }

    for _, row in df.iterrows():
        col0 = str(row[0]).strip().lower() if pd.notna(row[0]) else ""
        col1 = str(row[1]).strip().lower() if pd.notna(row[1]) else ""
        if not col1:
            continue

        # First logic
        # if any(k in col1 for k in ["location", "borehole"]):
        #     for idx in spec_col_indices:
        #         file_records[idx]["borehole"] = str(row[idx]).strip()

        # Second logic
        # if any(k in col1 for k in ["location", "borehole"]):
        #     # Test-level field: value only appears in one specimen column, but applies to all
        #     val = next((row[idx] for idx in spec_col_indices if pd.notna(row[idx]) and str(row[idx]).strip()), None)
        #     if val is not None:
        #         for idx in spec_col_indices:
        #             file_records[idx]["borehole"] = str(val).strip()

        # Third logic
        # Test Identification fields (Location/Borehole, Specimen, Depth) are
        # test-level, not per-specimen -- value appears in only ONE column but
        # applies to every specimen in the file.

        # NOTE: Location/Borehole/Depth are test-level fields (one column only) -> broadcast to all specimens
        if "test identification" in col0 or any(k in col1 for k in ["location", "borehole"]):
            val = next((row[idx] for idx in spec_col_indices if pd.notna(row[idx]) and str(row[idx]).strip()), None)
            if val is not None:
                if any(k in col1 for k in ["location", "borehole"]):
                    for idx in spec_col_indices:
                        file_records[idx]["borehole"] = str(val).strip()
                elif "depth" in col1:
                    for idx in spec_col_indices:
                        file_records[idx]["depth"] = val


        for canonical_name, aliases in features_to_extract.items():
            for alias in aliases:
                target_sec = alias[0].lower().strip()
                target_lab = alias[-1].lower().strip()
                if target_sec in col0 and target_lab == col1:
                    for idx in spec_col_indices:
                        val = row[idx]
                        if pd.notna(val) and "[" not in str(val):
                            file_records[idx][canonical_name] = val

    # NOTE: [N|M] etc. are character classes, "|" is literal here (not regex OR) -- works by coincidence for NWZ/HKW/TNW prefixes
    fn_bh_match = re.search(r'([N|M][W|Z][Z|W]-BH-\d+)', file_path.name, re.IGNORECASE)

    for idx in spec_col_indices:
        ctx = f"{file_records[idx].get('sample_type','')} {file_records[idx]['specimen_id']}".lower()

        if "undisturbed" in ctx: file_records[idx]["sample_type"] = "Undisturbed"
        elif "remoulded" in ctx: file_records[idx]["sample_type"] = "Remoulded"
        elif "re-compacted" in ctx or "recompacted" in ctx: file_records[idx]["sample_type"] = "Re-compacted"

        if not file_records[idx].get("borehole") and fn_bh_match:
            file_records[idx]["borehole"] = fn_bh_match.group(1).upper()

    all_data.extend(file_records.values())
    print(f"✅ Processed: {file_path.name}")

# %% 
# Dataframe assembly and initial cleaning
# ============================================================
#  DATAFRAME ASSEMBLY & CLEANING
# ============================================================

master_df = pd.DataFrame(all_data)

if 'borehole' in master_df.columns:
    master_df['borehole'] = (
        master_df['borehole']
        .astype(str)
        .str.upper()
        .str.replace('NZW', 'NWZ', regex=False)
        .str.strip()
    )

master_df = normalize_depth_column(master_df)
master_df['depth'] = pd.to_numeric(master_df['depth'], errors='coerce')

master_df["test_type"] = (
    master_df["source_file"]
    .str.split("_").str[6:].str.join("_")
    .str.replace(r"_GT04_V\d+_F.xlsx", "", regex=True)
    .str.replace(r"_V +_F.xlsx", "", regex=True)
    .str.replace(r"\d+", "", regex=True)
    .str.upper()
)

master_df["test_type"] = master_df["test_type"].apply(clean_test_type)

for col in ["borehole", "depth"]:
    master_df[col] = master_df.groupby("source_file")[col].ffill().bfill()

# %% 
# Aggregation
# ============================================================
#  AGGREGATION
# ============================================================

final_df = aggregate_specimens(master_df, borehole_col="borehole", depth_col="depth")

#%% 
# Simplification of phi and cohesion columns
final_df = simplify_geotechnical_data_phi_cohesion(final_df)

#%% Extract undrained shear strength components

# Execute
su_results = abs(final_df.apply(extract_su_dimensions, axis=1)) # Absolute to avoid negative su values (extension tests are negative)
final_df = pd.concat([final_df, su_results], axis=1)

# 4. Final Cleanup: Remove the requested source columns
cols_to_drop = [
    'undrained_shear_strength (kPa)', 
    'secant_modulus_e50_deviator_stress_peak_qf (kPa)']

# Using errors='ignore' in case the column names slightly differ by units
final_df = final_df.drop(columns=[c for c in final_df.columns if any(x in c for x in cols_to_drop)], errors='ignore')

#%% Safe averaging with scatter control (10% rule)

# --- APPLYING ---
cols_to_average = [
    'water_content (%)', 'bulk_density (Mg/m3)', 'dry_density (Mg/m3)', 
    'e0 (-)', 'torvane (kPa)', 'pocket_penetrometer (kPa)'
] # Index properties to average

# Apply the filter to each designated column
for col in cols_to_average:
    if col in final_df.columns:
        final_df[col] = final_df[col].apply(safe_average_with_scatter_control)

# Final look at the cleaned, averaged data
final_df

#%% E50ref calculation

# Apply the filter
if 'secant_modulus_e50 (kPa)' in final_df.columns:
    final_df = final_df.apply(filter_e50_by_test_type, axis=1)
else:
    # Fallback in case the column name varies slightly
    potential_cols = [c for c in final_df.columns if 'secant_modulus_e50' in c.lower()]
    if potential_cols:
        target_col_actual = potential_cols[0]
        def filter_dynamic(row):
            test_val = row.get('test_type', [])
            is_cd = any("CD" in str(t).upper() for t in test_val) if isinstance(test_val, list) else "CD" in str(test_val).upper()
            if not is_cd:
                row[target_col_actual] = np.nan
            return row
        final_df = final_df.apply(filter_dynamic, axis=1)
    else:
        final_df = final_df.copy()

# Execute E50ref optimization
# Apply to dataframe
m_optimization_df = final_df.apply(optimize_m_parameter, axis=1)
final_df = pd.concat([final_df, m_optimization_df], axis=1)
final_df


# %% Average numeric columns with scatter control
# ============================================================
#  AVERAGING WITH SCATTER CONTROL
# ============================================================

numeric_cols = [
    'water_content (%)', 'bulk_density (Mg/m3)', 'dry_density (Mg/m3)',
    'e0 (-)', 'torvane (kPa)', 'pocket_penetrometer (kPa)'
]

for col in numeric_cols:
    if col in final_df.columns:
        final_df[col] = final_df[col].apply(safe_average_with_scatter_control)


# %% Post-processing
# ============================================================
#  POST-PROCESSING
# ============================================================

export_df = final_df[['borehole', 'depth', 'test_type', 'source_file',
                         'water_content (%)', 'bulk_density (Mg/m3)', 'dry_density (Mg/m3)', 'e0 (-)', 'torvane (kPa)', 'pocket_penetrometer (kPa)', 
                         'phi_CD (degree)', 'cohesion_CD (kPa)', 'phi_RS_peak (degree)', 'phi_RS_residual (degree)', 
                         'su_UU_undisturbed (kPa)', 'su_UU_remoulded (kPa)', 'su_CU_undisturbed (kPa)', 'su_CU_remoulded (kPa)', 'su_CUe_undisturbed (kPa)', 
                         'secant_modulus_e50_sigma_eff_3 (kPa)', 'secant_modulus_e50 (kPa)', 'chosen_E50ref (kPa)', 'chosen_m']].copy()

# NOTE: drops NaN entries -- fine now since E50/sigma3 are already paired+cleaned in aggregate_specimens
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


# %% Export to CSV
output_file = _OWC_ROOT / "03_lab_data_cleaned" / "NWZ_soil_parameters.csv"
export_df.to_csv(output_file, index=False, encoding="utf-8")

print(f"✅ Extraction completed. Results saved to {output_file}")

# %%
