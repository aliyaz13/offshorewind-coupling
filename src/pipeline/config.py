"""
Configuration + path resolution - the single place the whole pipeline learns
where the data lives. Every stage imports PATHS / CONFIG from here instead of
hard-coding absolute paths.

Override the config file location with the OWC_CONFIG env var; otherwise the
repo-root config.yaml is used.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

# repo/src/pipeline/config.py  ->  parents[2] == repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG = _REPO_ROOT / "config.yaml"


def load_config(config_path: str | os.PathLike | None = None) -> dict:
    path = Path(config_path or os.environ.get("OWC_CONFIG", _DEFAULT_CONFIG))
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    data_root = Path(cfg.get("data_root", "data"))
    if not data_root.is_absolute():
        # relative paths resolve against the config file's own folder
        data_root = (path.parent / data_root).resolve()

    cfg["_data_root"] = data_root
    cfg["_config_path"] = path
    return cfg


CONFIG = load_config()


class Paths:
    """Resolves every folder / file the pipeline reads or writes."""

    def __init__(self, cfg: dict):
        self._cfg = cfg
        self.root: Path = cfg["_data_root"]

    # --- stage folders (match the repo's numbered layout) ---------------
    @property
    def cpt(self) -> Path:            return self.root / "01_cpt"
    @property
    def raw(self) -> Path:            return self.root / "02_lab_data_raw"
    @property
    def cleaned(self) -> Path:        return self.root / "03_lab_data_cleaned"
    @property
    def proximity(self) -> Path:      return self.root / "04_proximity_cpt_lab"
    @property
    def merge(self) -> Path:          return self.root / "05_merge_cpt_lab"

    # --- per-site / per-stage files -------------------------------------
    def raw_site(self, site: str) -> Path:
        return self.raw / site

    def cleaned_file(self, site: str) -> Path:
        """Stage A output == stage B02 soil input."""
        return self.cleaned / f"{site}_soil_parameters.csv"

    def cpt_merged(self, site: str) -> Path:
        return self.cpt / self._cfg["sites"][site]["cpt_merged"]

    def proximity_locations(self, site: str) -> Path:
        """Where the raw BH/CPT location files for stage B01 live."""
        return self.proximity / "locations" / site

    def matches_file(self, site: str) -> Path:
        """Stage B01 output == stage B02 mapping input."""
        return self.proximity / f"{site}_Borehole_and_CPT_Coordinates_Matches.csv"

    def proximity_plot(self, site: str) -> Path:
        return self.proximity / f"{site}_map.png"

    def coupled_file(self, site: str, approach: str) -> Path:
        """Stage B02 output == stage C input."""
        return self.merge / f"{site}_soil_cpt_{approach}.csv"

    def merged_file(self, approach: str) -> Path:
        """Stage C output."""
        return self.merge / f"merged_soil_cpt_{approach}.csv"

    def ensure(self) -> None:
        """Create the output folders if they don't exist yet."""
        for d in (self.cleaned, self.proximity, self.merge):
            d.mkdir(parents=True, exist_ok=True)


PATHS = Paths(CONFIG)


def sites() -> list[str]:
    return list(CONFIG["sites"].keys())


def approaches() -> list[str]:
    return list(CONFIG["coupling"].keys())
