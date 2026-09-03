# download – wiedergefundene Ergebnistabellen

Erzeugt gemäß `../search_prompt.md`. Vollständige Analyse: `../Fehlende_Ergebnisse_Report.md`.

Ein Unterordner pro Herkunftsexperiment (voller Ordnername inkl. Zeitstempel), damit
Herkunft eindeutig bleibt und keine Namenskollisionen auftreten.

**Solver-Namen:** In diesen Kopien wurde bei jedem Solver ohne Editions-Suffix das
Suffix aus der `version:` der zugehörigen Experiment-Solver-Config ergänzt
(`ICCMA21` → `_21`, `ICCMA19` → `_19`): `ASPARTIX-V_21`, `MatrixX_21`, `conarg_21`,
`fudge_21`, `pyglaf_21`, `A-Folio-DPDB_21`. Bereits eindeutige Namen
(`mu_toksia_21`, `EqArgSolver_19`, `coquiaas_I19`) unverändert. Die Original-Tabellen
in `results/**/evaluation/tables/` wurden nicht angefasst.

| Unterordner | Config | Report-Lücke |
|---|---|---|
| `ICCMA21-Solver-ICCMA21-DC-CO-RUN_2025-11-17_10-59-02/` | `configs/experiments/I21/I21.yaml` | Analyse_I21: ASPARTIX-V21/MatrixX/ConArg/FUDGE/µ-toksia21/pyglaf – DC-CO |
| `I23-PR-RERUN-RUN_2025-11-21_14-37-55/` | `configs/experiments/Missing_I15_Benchmark/I23.yaml` | Analyse_I23: EqArgSolver (2019) – SE/DC/DS-PR |
| `I23-ST-RERUN-RUN_2025-11-26_09-20-19/` | `configs/experiments/Missing_I15_Benchmark/I23-ST.yaml` | Analyse_I23: A-Folio DPDB & ConArg – SE/DC/DS-ST |
| `ZUSATZ_ohne_Config__ICCMA21-Solver-ICCMA21-RUN_2025-07-23_15-03-27/` | keine Config in `configs/experiments/` | Zusatzfund: pyglaf (2021) – DC-ID auf ICCMA21 |
