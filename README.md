# OffshoreWindRVO – Lab ↔ CPT coupling pipeline

Turns the standalone per-site scripts into one orchestrated pipeline. Every
path and parameter lives in **`config.yaml`**; the code has **no hard-coded
paths**.

```
A  process raw lab data   →  03_lab_data_cleaned/{SITE}_soil_parameters.csv
B01 BH↔CPT proximity      →  04_proximity_cpt_lab/{SITE}_..._Matches.csv
B02 couple soil ↔ CPT     →  05_merge_cpt_lab/{SITE}_soil_cpt_{approach}.csv
C  merge all sites        →  05_merge_cpt_lab/merged_soil_cpt_{approach}.csv
```

## Layout

```
offshorewind-coupling/
├── config.yaml                 # ← the only file you normally edit
├── run_pipeline.py             # orchestrator (A→B01→B02→C)
├── Makefile                    # `make all`, `make tnw`, …
├── requirements.txt
├── data/                       # your data (or point config.yaml elsewhere)
│   ├── 01_cpt/                 # CPT_db_15_..._{SITE}_merged.csv
│   ├── 02_lab_data_raw/        # HKW/ (csv), NWZ/ (xlsx), TNW/ (xlsx)
│   ├── 03_lab_data_cleaned/    # ← stage A output
│   ├── 04_proximity_cpt_lab/   # ← stage B01 output (+ locations/{SITE}/ inputs)
│   └── 05_merge_cpt_lab/       # ← stage B02 + C output
└── src/pipeline/
    ├── config.py               # config + path resolution (single source of truth)
    ├── common.py               # normalize_* + get_nearest_cpt* (was duplicated ×6)
    ├── a_process.py            # HKW native; NWZ/TNW run the preserved scrapers
    ├── b01_proximity.py        # headless (saves PNG, no plt.show)
    ├── b02_couple.py           # site- & approach-agnostic (replaces 6 scripts)
    ├── c_merge.py              # merges per approach, keeps all columns
    └── sites/
        ├── A_process_NWZ_raw.py   # original heavy scraper, paths injected
        └── A_process_TNW_raw.py   # original heavy scraper, paths injected
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Then edit `config.yaml`:
- `data_root:` – where your data tree lives (relative to the repo, or an
  absolute Nextcloud path).
- per-site `cpt_merged`, `id_normalization`, `proximity` files, `plot_limits`.
- `coupling` thresholds for `Appr01` / `Appr02`.

## Run

```bash
python run_pipeline.py                      # everything
python run_pipeline.py --sites TNW          # one site
python run_pipeline.py --approaches Appr02  # one approach
python run_pipeline.py --stages b02 c       # re-run coupling + merge only
python run_pipeline.py --keep-going         # don't abort on first failure
# or: make all / make tnw / make b02
```

Each stage is also runnable on its own:
```bash
python -m pipeline.b01_proximity --site TNW      # (run from src/)
python -m pipeline.b02_couple --site TNW --approach Appr02
```

## Expected input files per site

| Site | 02_lab_data_raw/            | 01_cpt/                                        | 04_.../locations/{SITE}/ |
|------|-----------------------------|------------------------------------------------|--------------------------|
| HKW  | 4× `HKW_*_cleaned.csv`      | `CPT_db_15_OffshoreWindRVO_HKW_merged.csv`     | `HKW_boreholes.ags`, `HKW_CPT.ags` |
| NWZ  | `*.xlsx` lab files          | `..._Nederwiek_20250117_merged.csv`            | `NWZ_BH.ags`, `NWZ_CPT.ags` |
| TNW  | `*.xlsx` lab files          | `..._TNW_merged.csv`                           | `TNW_boreholes.csv`, `TNW_cpt.ags` |

## What changed vs. the original scripts

- **Paths centralized** – all `C:\Users\niego\…` / `C:\Users\RYZEN 5\…` absolute
  paths removed; everything derives from `config.yaml → data_root`.
- **Consistent hand-offs** – stage A always writes `{SITE}_soil_parameters.csv`,
  which is exactly what B02 reads. B01→B02→C filenames now line up.
- **De-duplicated** – the `normalize_*` / `get_nearest_cpt*` functions live once
  in `common.py`; one `b02_couple.py` replaces the six per-site copies (the four
  empty `Appr0X_HKW/NWZ` stubs are no longer needed – just add the site to the
  run).
- **Headless** – B01 saves a PNG instead of a blocking `plt.show()`; TNW-specific
  axis limits moved to config.
- **Merge bug fixed** – `c_merge.py` globs the real B02 output folder and keeps
  every column (the old reindex silently dropped the Appr02 distance /
  depth-difference columns due to name drift).
- **Heavy scrapers preserved** – the 900/500-line NWZ & TNW `.xlsx` parsers are
  kept verbatim in `sites/`; only their input/output paths are injected.
```
