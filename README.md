# OffshoreWindRVO – Lab ↔ CPT Coupling Pipeline

Turns standalone per-site scripts into one orchestrated pipeline. All paths and
parameters live in **`config.yaml`**.

## Pipeline Stages

| Stage | Description | Output |
|-------|-------------|--------|
| **A** | Process raw lab data | `03_lab_data_cleaned/{SITE}_soil_parameters.csv` |
| **B01** | Borehole ↔ CPT proximity | `04_proximity_cpt_lab/{SITE}_..._Matches.csv` |
| **B02** | Couple soil ↔ CPT | `05_merge_cpt_lab/{SITE}_soil_cpt_{approach}.csv` |
| **C** | Merge all sites | `05_merge_cpt_lab/merged_soil_cpt_{approach}.csv` |

## Repository Layout

```
offshorewind-coupling/
├── config.yaml                 # ← the only file you normally edit
├── run_pipeline.py             # orchestrator (A → B01 → B02 → C)
├── Makefile                    # `make all`, `make tnw`, …
├── requirements.txt
├── data/                       # Input and generated data (or point config.yaml elsewhere)
│   ├── 01_cpt/                 # CPT_db_15_..._{SITE}_merged.csv
│   ├── 02_lab_data_raw/        # HKW/ (csv), NWZ/ (xlsx), TNW/ (xlsx)
│   ├── 03_lab_data_cleaned/    # ← stage A output
│   ├── 04_proximity_cpt_lab/
│   │   └── locations/{SITE}/   # ← borehole & CPT location files (input to stage B01, see table below)
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

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

Before running the pipeline, update `config.yaml` to match your local setup:

- `data_root:` — where your data tree lives (relative to the repo)
- per-site `cpt_merged`, `id_normalization`, `proximity` files, `plot_limits`
- `coupling` thresholds for `Appr01` / `Appr02`

## Usage

### Common commands

```bash
python run_pipeline.py                      # everything
python run_pipeline.py --sites TNW          # one site
python run_pipeline.py --approaches Appr02  # one approach
python run_pipeline.py --stages b02 c       # re-run coupling + merge only
python run_pipeline.py --keep-going         # don't abort on first failure
# or: make all / make tnw / make b02
```

### Run individual stages standalone

```bash
python -m pipeline.b01_proximity --site TNW      # (run from src/)
python -m pipeline.b02_couple --site TNW --approach Appr02
```

## Recommended Development Workflow

**Full run, one approach at a time:**

```bash
# 1. Process laboratory data
python run_pipeline.py --stages a

# 2. Compute borehole ↔ CPT proximity
python run_pipeline.py --stages b01

# 3. Couple using Approach 1
python run_pipeline.py --stages b02 --approaches Appr01

# 4. Merge all sites (Approach 1)
python run_pipeline.py --stages c --approaches Appr01

# 5. Couple using Approach 2
python run_pipeline.py --stages b02 --approaches Appr02

# 6. Merge all sites (Approach 2)
python run_pipeline.py --stages c --approaches Appr02
```

**Single-site workflow:**

```bash
python run_pipeline.py --stages a   --sites TNW
python run_pipeline.py --stages b01 --sites TNW
python run_pipeline.py --stages b02 --sites TNW --approaches Appr01
python run_pipeline.py --stages c   --approaches Appr01
```

## Expected Input Files Per Site

| Site | `02_lab_data_raw/` | `01_cpt/` | `04_.../locations/{SITE}/` |
|------|---------------------|-----------|------------------------------|
| HKW  | 4× `HKW_*_cleaned.csv` | `CPT_db_15_OffshoreWindRVO_HKW_merged.csv` | `HKW_boreholes.ags`, `HKW_CPT.ags` |
| NWZ  | `*.xlsx` lab files  | `..._Nederwiek_20250117_merged.csv` | `NWZ_BH.ags`, `NWZ_CPT.ags` |
| TNW  | `*.xlsx` lab files  | `..._TNW_merged.csv` | `TNW_boreholes.csv`, `TNW_cpt.ags` |
