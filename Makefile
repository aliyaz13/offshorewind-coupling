# Convenience wrapper around run_pipeline.py
PY ?= python

.PHONY: all a b01 b02 c tnw hkw nwz clean

all:            ## run the full pipeline (all sites, both approaches)
	$(PY) run_pipeline.py

a:              ## stage A only (all sites)
	$(PY) run_pipeline.py --stages a
b01:            ## stage B01 only
	$(PY) run_pipeline.py --stages b01
b02:            ## stage B02 only
	$(PY) run_pipeline.py --stages b02
c:              ## stage C only
	$(PY) run_pipeline.py --stages c

tnw:            ## everything for TNW
	$(PY) run_pipeline.py --sites TNW
hkw:            ## everything for HKW
	$(PY) run_pipeline.py --sites HKW
nwz:            ## everything for NWZ
	$(PY) run_pipeline.py --sites NWZ

clean:          ## remove generated outputs (03/04/05)
	rm -f data/03_lab_data_cleaned/*.csv
	rm -f data/04_proximity_cpt_lab/*.csv data/04_proximity_cpt_lab/*.png
	rm -f data/05_merge_cpt_lab/*.csv
