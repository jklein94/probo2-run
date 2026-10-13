"""
Running updates: evaluate each job as soon as it finishes.

After a job (solver x benchmark x task) has finished, its results.csv is evaluated
and the statistics are written into a per-(benchmark, task) table in
`cfg.running_updates_dir`:

    running_updates/<benchmark_name>_<task>.csv   machine readable, one row per solver
    running_updates/<benchmark_name>_<task>.txt   pretty-printed version of the same table

The statistics mirror the final evaluation callbacks (solved, timeouts, errors, invalid,
coverage, PAR2, PAR10, mean runtimes), so the running tables show the same numbers the
final evaluation will report for that combination - without waiting for the whole sweep.

The tables are shared by all jobs of a sweep, so every update is done under an exclusive
file lock (safe for parallel launchers such as joblib).
"""
import fcntl
import io
import os
from datetime import datetime

import pandas as pd
import tabulate
from hydra.core.hydra_config import HydraConfig
from omegaconf import DictConfig
from rich.console import Console

from src import utils
from src.callbacks.statistics_callbacks import calculate_par_score

console = Console()

# Identifies one row (= one job result) within a (benchmark, task) table
ROW_KEY = ["solver_name", "variant", "run"]


def get_job_result_file(cfg: DictConfig) -> str:
    """Returns the path of the results file written by the current job."""
    hydra_config = HydraConfig.get()
    output_root_dir = os.path.join(hydra_config.runtime.output_dir, hydra_config.output_subdir)
    return os.path.join(output_root_dir, utils.get_solver_output_file_name(cfg))


def compute_job_statistics(df: pd.DataFrame, timeout: int) -> pd.DataFrame:
    """
    Computes the evaluation statistics for the rows of a single job's results file.
    Uses the same definitions as the statistics callbacks in
    src/callbacks/statistics_callbacks.py.
    """
    df = df.copy()
    df["solved"] = (
        (~df["timed_out"]) & (~df["exit_with_error"]) & (df["solver_output_valid"])
    ).astype(int)
    keys = ["task", "benchmark_name", "solver_name"]
    stats = (
        df.groupby(keys)
        .agg(
            instances=("instance", "count"),
            solved=("solved", "sum"),
            timeouts=("timed_out", lambda x: x.sum()),
            errors=("exit_with_error", lambda x: x.sum()),
            invalid=("solver_output_valid", lambda x: (~x).sum()),
            coverage=("solver_output_valid", lambda x: x.mean()),
            mean_perfcounter_time=("perfcounter_time", "mean"),
            mean_user_sys_time=("user_sys_time", "mean"),
        )
        .reset_index()
    )
    for alpha in (2, 10):
        stats = stats.merge(calculate_par_score(df, timeout, alpha), on=keys, how="left")
    return stats


def update_running_tables(cfg: DictConfig) -> None:
    """
    Evaluates the results of the job that just finished and inserts/updates its row in
    the running table of the corresponding (benchmark, task) combination.
    """
    result_file = get_job_result_file(cfg)
    if not os.path.exists(result_file) or os.path.getsize(result_file) == 0:
        return

    df = pd.read_csv(result_file)
    if df.empty:
        return

    stats = compute_job_statistics(df, cfg.timeout)
    variant = os.path.splitext(os.path.basename(result_file))[0].removeprefix("results").lstrip("_")
    stats.insert(3, "variant", variant)
    stats.insert(4, "run", cfg.runs)
    stats["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    out_dir = cfg.running_updates_dir
    os.makedirs(out_dir, exist_ok=True)
    base_name = f"{cfg.benchmark.name}_{cfg.task}"
    csv_path = os.path.join(out_dir, base_name + ".csv")
    txt_path = os.path.join(out_dir, base_name + ".txt")

    with open(csv_path, "a+", newline="", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            content = f.read()
            if content.strip():
                table = pd.read_csv(io.StringIO(content), keep_default_na=False)
                table["variant"] = table["variant"].astype(str)
                # Replace an existing row of the same job (e.g. a re-run) instead of duplicating it
                merged = table.merge(stats[ROW_KEY], on=ROW_KEY, how="left", indicator=True)
                table = table[(merged["_merge"] == "left_only").values]
                table = pd.concat([table, stats], ignore_index=True)
            else:
                table = stats
            table = table.sort_values(
                ["solved", "PAR_2"], ascending=[False, True]
            ).reset_index(drop=True)

            f.seek(0)
            f.truncate()
            table.to_csv(f, index=False)
            f.flush()

            with open(txt_path, "w", encoding="utf-8") as txt:
                txt.write(
                    f"Running results: {cfg.benchmark.name} / {cfg.task} "
                    f"(timeout {cfg.timeout}s, last update {stats['last_update'].iloc[0]})\n"
                )
                txt.write(
                    tabulate.tabulate(
                        table.drop(columns=["task", "benchmark_name"]).round(3),
                        headers="keys",
                        tablefmt="pretty",
                        showindex=False,
                    )
                )
                txt.write("\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

    console.print(
        f"[bold green]✔ Running update:[/bold green] {cfg.solver.name} on "
        f"{cfg.benchmark.name}/{cfg.task} -> {csv_path}"
    )
    console.print(
        table[["solver_name", "variant", "run", "instances", "solved", "timeouts", "errors", "PAR_2"]]
        .to_string(index=False)
    )
