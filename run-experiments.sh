#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Verwendung: $0 <Experiments-Ordner>" >&2
    exit 1
fi

experiment_dir="${1%/}"

if [[ ! -d "$experiment_dir" ]]; then
    echo "Fehler: Ordner existiert nicht: $experiment_dir" >&2
    exit 1
fi

dir_name="$(basename "$experiment_dir")"
log_dir="logs"
found=false

mkdir -p "$log_dir"

while IFS= read -r -d '' yaml_file; do
    found=true

    file_name="$(basename "$yaml_file")"
    yaml_name="${file_name%.*}"
    experiment_config="${dir_name}/${file_name}"
    log_file="${log_dir}/${yaml_name}.out"

    echo "Starte Experiment: ${experiment_config}"
    echo "Logdatei: ${log_file}"

    nohup python probo2-run.py \
        -m "+experiments=${experiment_config}" \
        >"$log_file" 2>&1 < /dev/null &

    experiment_pid=$!

    echo "PID: ${experiment_pid}"
    echo "Warte auf Abschluss des Experiments ..."

    wait "$experiment_pid"

    echo "Experiment abgeschlossen: ${experiment_config}"
    echo
done < <(
    find "$experiment_dir" \
        -maxdepth 1 \
        -type f \
        \( -name '*.yaml' -o -name '*.yml' \) \
        -print0 \
        | sort -z
)

if [[ "$found" == false ]]; then
    echo "Keine YAML-Dateien in '$experiment_dir' gefunden." >&2
    exit 1
fi

echo "Alle Experimente wurden nacheinander abgeschlossen."