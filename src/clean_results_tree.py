#!/usr/bin/env python3
import csv
import sys
from pathlib import Path


def is_true(value) -> bool:
    """Interpret common truthy string/boolean values als True."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("true", "1", "yes", "y")


def choose_row_for_result_path(rows):
    """
    rows: Liste von Dicts (alle mit demselben result_path).
    Auswahl-Priorität:
      1. solver_output_valid == True  -> reason = "valid"
      2. sonst timed_out == True      -> reason = "timeout"
      3. sonst erste Zeile            -> reason = "fallback"
    """
    valid_rows = [r for r in rows if is_true(r.get("solver_output_valid"))]
    if valid_rows:
        return valid_rows[0], "valid"

    timed_out_rows = [r for r in rows if is_true(r.get("timed_out"))]
    if timed_out_rows:
        return timed_out_rows[0], "timeout"

    return rows[0], "fallback"


def clean_csv(input_path: Path, output_path: Path):
    """
    Bereinigt eine einzelne CSV-Datei.

    Liest aus input_path, schreibt nach output_path.
    Gibt (output_path, stats_dict) zurück.
    """
    with input_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            raise ValueError(f"CSV {input_path} hat keine Header / fieldnames.")

        groups = {}
        for row in reader:
            key = row.get("result_path")
            if key is None:
                raise ValueError(
                    f"Zeile ohne 'result_path' in Datei {input_path} gefunden."
                )
            groups.setdefault(key, []).append(row)

    total_rows = sum(len(rows) for rows in groups.values())
    unique_result_paths = len(groups)
    duplicate_groups = sum(1 for rows in groups.values() if len(rows) > 1)
    removed_rows = total_rows - unique_result_paths

    chosen_via_valid = 0
    chosen_via_timeout = 0
    chosen_via_fallback = 0

    cleaned_rows = []
    for key, rows in groups.items():
        if len(rows) == 1:
            cleaned_rows.append(rows[0])
        else:
            chosen, reason = choose_row_for_result_path(rows)
            cleaned_rows.append(chosen)
            if reason == "valid":
                chosen_via_valid += 1
            elif reason == "timeout":
                chosen_via_timeout += 1
            else:
                chosen_via_fallback += 1

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cleaned_rows)

    stats = {
        "total_rows": total_rows,
        "unique_result_paths": unique_result_paths,
        "duplicate_groups": duplicate_groups,
        "removed_rows": removed_rows,
        "chosen_via_valid": chosen_via_valid,
        "chosen_via_timeout": chosen_via_timeout,
        "chosen_via_fallback": chosen_via_fallback,
    }

    return output_path, stats


def process_solver_dir(solver_dir: Path):
    """
    Läuft rekursiv durch einen *einzelnen* Solver-Ordner und
    bereinigt alle Dateien namens 'results.csv'.

    Dabei gilt:
      - ursprüngliche results.csv -> _old_results.csv
      - bereinigte Version        -> results.csv
    """
    if not solver_dir.is_dir():
        raise ValueError(f"'{solver_dir}' ist kein Verzeichnis.")

    print(f"== Solver-Ordner: {solver_dir} ==")

    csv_paths = list(solver_dir.rglob("results.csv"))
    print(f"  Gefundene results.csv-Dateien: {len(csv_paths)}")

    solver_stats = {
        "num_csv": 0,
        "total_rows": 0,
        "total_removed": 0,
        "total_duplicate_groups": 0,
    }

    if not csv_paths:
        print(f"  -> Keine 'results.csv' in {solver_dir} gefunden.\n")
        return solver_stats

    for path in csv_paths:
        print(f"  Verarbeite Datei: {path}")

        try:
            # Original -> _old_results.csv
            old_path = path.with_name("_old_results.csv")
            if old_path.exists():
                print("    Hinweis: '_old_results.csv' existiert bereits und wird überschrieben.")
                old_path.unlink()

            print(f"    Benenne Original um: {path.name} -> {old_path.name}")
            path.rename(old_path)

            # Bereinigte Version wieder als results.csv
            new_results_path = path  # gleicher Pfad/Name wie vorher

            output_path, stats = clean_csv(old_path, new_results_path)

            print(f"    Gesamtzeilen (alt):     {stats['total_rows']}")
            print(f"    Eindeutige result_path: {stats['unique_result_paths']}")
            print(f"    Duplikat-Gruppen:       {stats['duplicate_groups']}")
            print(f"    Entfernte Zeilen:       {stats['removed_rows']}")
            print(
                f"    Auswahlgründe:"
                f" valid={stats['chosen_via_valid']},"
                f" timeout={stats['chosen_via_timeout']},"
                f" fallback={stats['chosen_via_fallback']}"
            )
            print(f"    -> Backup-Datei:        {old_path}")
            print(f"    -> Bereinigte Datei:    {output_path}\n")

            # Aggregation pro Solver-Ordner
            solver_stats["num_csv"] += 1
            solver_stats["total_rows"] += stats["total_rows"]
            solver_stats["total_removed"] += stats["removed_rows"]
            solver_stats["total_duplicate_groups"] += stats["total_duplicate_groups"]

        except Exception as e:
            print(f"    FEHLER beim Verarbeiten von {path}: {e}", file=sys.stderr)

    print("  Zusammenfassung für Solver-Ordner:")
    print(f"    Verarbeitete CSV-Dateien:    {solver_stats['num_csv']}")
    print(f"    Gesamtzeilen (vorher):       {solver_stats['total_rows']}")
    print(f"    Entfernte Zeilen gesamt:     {solver_stats['total_removed']}")
    print(f"    Duplikat-Gruppen gesamt:     {solver_stats['total_duplicate_groups']}")
    print()
    return solver_stats


def process_root_with_solvers(root_dir: Path):
    """
    Erwartet ein Verzeichnis, in dem mehrere Solver-Ordner liegen.
    Beispiel:

    root_dir/
        solver_A/
        solver_B/
        ...

    Für jeden Unterordner wird process_solver_dir aufgerufen.
    """
    if not root_dir.is_dir():
        raise ValueError(f"'{root_dir}' ist kein Verzeichnis.")

    print(f"Starte Verarbeitung des Root-Verzeichnisses: {root_dir}\n")

    solver_dirs = [d for d in root_dir.iterdir() if d.is_dir()]
    print(f"Gefundene Solver-Ordner: {len(solver_dirs)}\n")

    if not solver_dirs:
        print(f"Keine Unterordner in {root_dir} gefunden.")
        return

    total_stats = {
        "num_solvers": 0,
        "num_csv": 0,
        "total_rows": 0,
        "total_removed": 0,
        "total_duplicate_groups": 0,
    }

    for solver_dir in solver_dirs:
        solver_stats = process_solver_dir(solver_dir)
        total_stats["num_solvers"] += 1
        total_stats["num_csv"] += solver_stats["num_csv"]
        total_stats["total_rows"] += solver_stats["total_rows"]
        total_stats["total_removed"] += solver_stats["total_removed"]
        total_stats["total_duplicate_groups"] += solver_stats["total_duplicate_groups"]

    print("===== Gesamtzusammenfassung =====")
    print(f"Anzahl Solver-Ordner:        {total_stats['num_solvers']}")
    print(f"Anzahl verarbeiteter CSVs:   {total_stats['num_csv']}")
    print(f"Gesamtzeilen (vorher):       {total_stats['total_rows']}")
    print(f"Entfernte Zeilen gesamt:     {total_stats['total_removed']}")
    print(f"Duplikat-Gruppen gesamt:     {total_stats['total_duplicate_groups']}")
    print("Fertig.")


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} ROOT_DIR_WITH_SOLVERS", file=sys.stderr)
        sys.exit(1)

    root_dir = Path(sys.argv[1])

    try:
        process_root_with_solvers(root_dir)
    except Exception as e:
        print(f"Fehler: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
