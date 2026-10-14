#!/usr/bin/env python3
"""
Progress overview for a (running or finished) probo2 experiment.

Reads only - nothing in the experiment directory is written or changed, so it is safe to
call while the experiment is running. Typical use:

    watch -n 30 python progress.py                      # experiment started last (results/.current_experiment)
    watch -n 30 python progress.py results/<experiment_dir>

Sources:
    multirun.yaml                     sweep (solver/benchmark/task/runs), timeout, run_subset,
                                      solver_task_mapping, launcher parallelism
    configs/solver, configs/benchmark solver path/format, benchmark path/format (expected instances)
    solver_results/**/results*.csv    one row per finished instance (written right after each instance)
    result_file_index.txt             jobs that have started
    combined_results.csv              exists once the whole sweep has finished

Statistics use the same definitions as the evaluation (src/running_updates.compute_job_statistics).
Time estimates simulate the remaining jobs on the available parallel slots (each job runs its
instances sequentially): "erwartet" uses the mean runtime per instance observed so far,
"maximal" assumes every remaining instance runs into the timeout.
"""
import argparse
import contextlib
import io
import glob
import os
import re
import sys
from datetime import datetime, timedelta

import pandas as pd
import psutil
import tabulate
import yaml
from omegaconf import OmegaConf

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_DIR)

from src import utils  # noqa: E402
from src.running_updates import compute_job_statistics  # noqa: E402

CONFIG_DIR = os.path.join(REPO_DIR, "configs")
STATUS_ORDER = {"läuft": 0, "wartet": 1, "fertig": 2}


# ---------------------------------------------------------------- formatting helpers

def fmt_duration(seconds) -> str:
    if seconds is None:
        return "–"
    seconds = int(max(seconds, 0))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h {minutes:02d}m"
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def fmt_clock(dt: datetime, now: datetime) -> str:
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    return dt.strftime("%d.%m. %H:%M")


def progress_bar(fraction: float, width: int = 30) -> str:
    fraction = min(max(fraction, 0.0), 1.0)
    filled = int(round(fraction * width))
    return "█" * filled + "░" * (width - filled)


# ---------------------------------------------------------------- experiment discovery

def read_current_experiment():
    """Returns the experiment recorded by probo2-run.py in utils.CURRENT_EXPERIMENT_FILE, if it still exists."""
    try:
        with open(utils.CURRENT_EXPERIMENT_FILE, encoding="utf-8") as f:
            path = f.read().strip()
    except OSError:
        return None
    if path and os.path.isfile(os.path.join(path, "multirun.yaml")):
        return path
    return None


def find_newest_experiment(results_dir: str) -> str:
    candidates = glob.glob(os.path.join(results_dir, "*", "multirun.yaml")) + glob.glob(
        os.path.join(results_dir, "*", "*", "multirun.yaml")
    )
    if not candidates:
        sys.exit(f"Kein Experiment (multirun.yaml) unter {results_dir} gefunden.")
    # The start timestamp in the directory name is reliable; directory mtimes change on later edits
    return max((os.path.dirname(p) for p in candidates), key=parse_start_time)


def parse_start_time(experiment_dir: str):
    match = re.search(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})$", os.path.basename(experiment_dir.rstrip("/")))
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%d_%H-%M-%S")
    return datetime.fromtimestamp(os.path.getctime(experiment_dir))


def sweep_values(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value]
    return [v.strip() for v in str(value).split(",") if v.strip()]


def load_group_config(group: str, choice: str):
    """Returns the config of a sweep choice, or None if it no longer exists (e.g. renamed since the run)."""
    path = os.path.join(CONFIG_DIR, group, choice.strip("/") + ".yaml")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def parallel_slots(launcher: dict) -> int:
    if not launcher:
        return 1
    if "ray" in launcher:
        ray = launcher["ray"] or {}
        total = (ray.get("init") or {}).get("num_cpus") or os.cpu_count()
        per_job = (ray.get("remote") or {}).get("num_cpus") or 1
        return max(int(total // per_job), 1)
    if launcher.get("n_jobs"):
        n_jobs = int(launcher["n_jobs"])
        return n_jobs if n_jobs > 0 else os.cpu_count()
    return 1


class _HydraChoiceShim:
    """Lets utils.task_allowed_for_solver resolve the benchmark config-group name outside of Hydra."""

    def __init__(self, benchmark_choice: str):
        self.runtime = OmegaConf.create({"choices": {"benchmark": benchmark_choice}})

    def get(self):
        return self


def mapping_allows(mapping, solver_name: str, benchmark_choice: str, benchmark_name: str, task: str) -> bool:
    cfg = OmegaConf.create(
        {"solver": {"name": solver_name}, "benchmark": {"name": benchmark_name}, "task": task,
         "solver_task_mapping": mapping or {}}
    )
    original = utils.HydraConfig
    utils.HydraConfig = _HydraChoiceShim(benchmark_choice)
    try:
        return utils.task_allowed_for_solver(cfg, task)
    finally:
        utils.HydraConfig = original


def count_instances(benchmark: dict, solver: dict, run_subset) -> int:
    fmt = utils.get_matching_format(solver.get("format"), benchmark.get("format"))
    if fmt is None:
        return 0
    instances = utils.get_files_with_extension(benchmark["path"], fmt)
    if run_subset is not False and run_subset is not None:
        if isinstance(run_subset, int):
            instances = instances[:run_subset]
        elif os.path.isfile(str(run_subset)):
            with open(run_subset, encoding="utf-8") as f:
                subset = set(f.read().splitlines())
            instances = [i for i in instances if os.path.splitext(os.path.basename(i))[0] in subset]
    return len(instances)


# ---------------------------------------------------------------- job collection

def sweep_params(cfg: dict) -> dict:
    """Sweep values from the experiment config, overridden by command-line overrides (e.g. task=DC-CO,DS-CO)."""
    params = dict(cfg["hydra"].get("sweeper", {}).get("params") or {})
    for override in (cfg["hydra"].get("overrides") or {}).get("task") or []:
        key, sep, value = str(override).partition("=")
        key = key.lstrip("+~")
        if sep and key in ("solver", "benchmark", "task", "runs"):
            params[key] = value
    return params


def collect_jobs(experiment_dir: str, cfg: dict, finished: bool) -> tuple:
    params = sweep_params(cfg)
    runs = sweep_values(params.get("runs")) or [str(cfg.get("runs", 1))]
    mapping = cfg.get("solver_task_mapping") or {}
    run_subset = cfg.get("run_subset", False)

    index_file = os.path.join(experiment_dir, "result_file_index.txt")
    started = set()
    if os.path.isfile(index_file):
        with open(index_file, encoding="utf-8") as f:
            started = {os.path.abspath(line.strip()) for line in f if line.strip()}

    jobs, skipped, unsupported, missing, support_cache = [], 0, [], [], {}
    instance_cache = {}
    for solver_choice in sweep_values(params.get("solver")):
        solver = load_group_config("solver", solver_choice)
        if solver is None:
            missing.append(f"solver/{solver_choice.strip('/')}")
            continue
        for benchmark_choice in sweep_values(params.get("benchmark")):
            benchmark = load_group_config("benchmark", benchmark_choice)
            if benchmark is None:
                missing.append(f"benchmark/{benchmark_choice.strip('/')}")
                continue
            for task in sweep_values(params.get("task")):
                if not mapping_allows(mapping, solver["name"], benchmark_choice, benchmark["name"], task):
                    skipped += len(runs)
                    continue
                key = (solver_choice, benchmark_choice)
                if key not in instance_cache:
                    instance_cache[key] = count_instances(benchmark, solver, run_subset)
                for run in runs:
                    job_dir = os.path.join(experiment_dir, "solver_results", solver["name"], benchmark["name"], run, task)
                    result_files = sorted(glob.glob(os.path.join(job_dir, "results*.csv")))
                    is_started = bool(result_files) or any(p.startswith(os.path.abspath(job_dir) + os.sep) for p in started)
                    if not is_started and not finished:
                        # Jobs whose task the solver does not support never start; check only those
                        support_key = (solver["path"], task)
                        if support_key not in support_cache:
                            with contextlib.redirect_stdout(io.StringIO()):
                                support_cache[support_key] = utils.solver_supports_task(solver["path"], task)
                        if not support_cache[support_key]:
                            unsupported.append(f"{solver['name']} / {task}")
                            continue
                    jobs.append({
                        "solver": solver["name"], "benchmark": benchmark_choice, "task": task, "run": run,
                        "expected": instance_cache[key], "result_files": result_files, "started": is_started,
                    })
    return jobs, skipped, sorted(set(unsupported)), sorted(set(missing))


def read_results(result_files: list) -> pd.DataFrame:
    frames = []
    for path in result_files:
        try:
            if os.path.getsize(path) > 0:
                frames.append(pd.read_csv(path))
        except (pd.errors.EmptyDataError, pd.errors.ParserError, OSError):
            # The file may be appended to while we read it; the next refresh will pick it up
            continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset="result_path", keep="last")
    for column in ("timed_out", "exit_with_error", "solver_output_valid"):
        df[column] = df[column].astype(str).str.lower().eq("true")
    return df


# ---------------------------------------------------------------- time estimate

def simulate_finish(slots: int, running: list, pending: list) -> float:
    """Remaining wall time when running jobs keep their slot and pending jobs fill free slots in order."""
    free_at = sorted(running)[:slots]
    free_at += [0.0] * (slots - len(free_at))
    for duration in pending:
        free_at.sort()
        free_at[0] += duration
    return max(free_at) if free_at else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Fortschritt eines probo2-Experiments anzeigen.")
    parser.add_argument(
        "experiment_dir", nargs="?",
        help="Ergebnisordner (Standard: zuletzt gestartetes Experiment aus results/.current_experiment, "
             "sonst das neueste in results/)",
    )
    parser.add_argument("--active", action="store_true", help="Nur laufende und wartende Jobs in der Tabelle zeigen")
    args = parser.parse_args()

    experiment_dir = os.path.abspath(
        args.experiment_dir
        or read_current_experiment()
        or find_newest_experiment(os.path.join(REPO_DIR, "results"))
    )
    multirun_file = os.path.join(experiment_dir, "multirun.yaml")
    if not os.path.isfile(multirun_file):
        sys.exit(f"Keine multirun.yaml in {experiment_dir}")
    with open(multirun_file, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    now = datetime.now()
    timeout = float(cfg.get("timeout", 600))
    slots = parallel_slots(cfg["hydra"].get("launcher"))
    start = parse_start_time(experiment_dir)
    combined = os.path.join(experiment_dir, "combined_results.csv")
    finished = os.path.isfile(combined)
    jobs, skipped, unsupported, missing = collect_jobs(experiment_dir, cfg, finished)

    # A finished sweep ends with its last instance result (combined_results.csv may be rewritten later)
    last_write = max((os.path.getmtime(p) for j in jobs for p in j["result_files"]), default=None)
    end = datetime.fromtimestamp(last_write) if finished and last_write else now
    elapsed = (end - start).total_seconds()
    never_started = [j for j in jobs if finished and not j["started"]]
    jobs = [j for j in jobs if not (finished and not j["started"])]

    all_rows = []
    for job in jobs:
        df = read_results(job["result_files"])
        job["df"] = df
        job["done"] = len(df)
        job["last_result"] = max((os.path.getmtime(p) for p in job["result_files"]), default=None)
        if job["done"] >= job["expected"]:
            job["status"] = "fertig"
        elif job["started"] and not finished:
            job["status"] = "läuft"
        elif finished:
            job["status"] = "fertig"  # sweep is over; missing instances are reported below
        else:
            job["status"] = "wartet"
        if not df.empty:
            all_rows.append(df)
    all_df = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()

    # Mean runtime per instance: per job if it has enough data, else per task, else overall
    overall_mean = all_df["perfcounter_time"].mean() if not all_df.empty else None
    task_mean = all_df.groupby("task")["perfcounter_time"].mean().to_dict() if not all_df.empty else {}

    running_expected, running_max, pending_expected, pending_max = [], [], [], []
    for job in jobs:
        remaining = max(job["expected"] - job["done"], 0)
        if job["done"] >= 5:
            mean = job["df"]["perfcounter_time"].mean()
        else:
            mean = task_mean.get(job["task"], overall_mean)
        job["mean_estimate"] = mean
        if job["status"] == "fertig" or remaining == 0:
            job["rest"] = 0.0
            continue
        # Time already spent on the instance that is currently being solved
        since_last = 0.0
        if job["status"] == "läuft":
            reference = job["last_result"] or start.timestamp()
            since_last = max(now.timestamp() - reference, 0.0)
        est = None if mean is None else max(remaining * mean - min(since_last, mean), 0.0)
        worst = max(remaining * timeout - min(since_last, timeout), 0.0)
        job["rest"] = est
        if job["status"] == "läuft":
            running_expected.append(est)
            running_max.append(worst)
        else:
            pending_expected.append(est)
            pending_max.append(worst)

    expected_total = sum(j["expected"] for j in jobs)
    done_total = sum(min(j["done"], j["expected"]) for j in jobs)
    fraction = done_total / expected_total if expected_total else 1.0
    counts = {s: sum(1 for j in jobs if j["status"] == s) for s in STATUS_ORDER}

    # ------------------------------------------------------------ header
    out = []
    state = "ABGESCHLOSSEN" if finished else "LÄUFT"
    out.append(f"{cfg.get('name', os.path.basename(experiment_dir))}   [{state}]")
    out.append(f"Ordner      {os.path.relpath(experiment_dir, os.getcwd())}")
    out.append(
        f"Start       {fmt_clock(start, now)}   Laufzeit {fmt_duration(elapsed)}   "
        f"Timeout {int(timeout)}s   parallel {slots}"
    )
    out.append(
        f"Fortschritt {progress_bar(fraction)} {done_total:,} / {expected_total:,} Instanzen ({fraction:.1%})".replace(",", ".")
    )
    out.append(
        f"Jobs        {counts['fertig']} fertig · {counts['läuft']} laufen · {counts['wartet']} warten"
        f"   (übersprungen per Mapping: {skipped})"
    )
    if elapsed > 0 and done_total and not finished:
        out.append(f"Tempo       {done_total / elapsed * 3600:.1f} Instanzen/h")

    if not finished and done_total < expected_total:
        worst = simulate_finish(slots, running_max, pending_max)
        if None in running_expected or None in pending_expected:
            expected_line = "erwartet –  (noch keine abgeschlossene Instanz)"
        else:
            remaining = simulate_finish(slots, running_expected, pending_expected)
            expected_line = f"erwartet ~{fmt_duration(remaining)} (fertig ~{fmt_clock(now + timedelta(seconds=remaining), now)})"
        out.append(
            f"Restzeit    {expected_line}   |   maximal {fmt_duration(worst)} "
            f"(fertig spätestens {fmt_clock(now + timedelta(seconds=worst), now)})"
        )

    if not all_df.empty:
        stats = compute_job_statistics(all_df, timeout)
        solved, timeouts = int(stats["solved"].sum()), int(stats["timeouts"].sum())
        errors, invalid = int(stats["errors"].sum()), int(stats["invalid"].sum())
        out.append(
            f"Bisher      gelöst {solved} · Timeouts {timeouts} · Fehler {errors} · ungültig {invalid}"
            f" · Ø Zeit {all_df['perfcounter_time'].mean():.1f}s"
        )

    # ------------------------------------------------------------ job table
    table = []
    shown = [j for j in jobs if not args.active or j["status"] != "fertig"]
    shown.sort(key=lambda j: (STATUS_ORDER[j["status"]], j["solver"], j["benchmark"], j["task"], j["run"]))
    for job in shown:
        row = [job["solver"], job["benchmark"], job["task"]]
        if len({j["run"] for j in jobs}) > 1:
            row.append(job["run"])
        row += [job["status"], f"{job['done']}/{job['expected']}"]
        if job["df"].empty:
            row += ["–"] * 6
        else:
            s = compute_job_statistics(job["df"], timeout).iloc[0]
            row += [int(s["solved"]), int(s["timeouts"]), int(s["errors"]), int(s["invalid"]),
                    f"{s['PAR_2']:.1f}", f"{s['mean_perfcounter_time']:.1f}s"]
        row.append(fmt_duration(job["rest"]) if job["status"] != "fertig" else "")
        table.append(row)
    headers = ["Solver", "Benchmark", "Task"]
    if len({j["run"] for j in jobs}) > 1:
        headers.append("Run")
    headers += ["Status", "fertig", "gelöst", "TO", "Err", "Inv", "PAR2", "Ø Zeit", "Rest ~"]
    out.append("")
    out.append(tabulate.tabulate(table, headers=headers, tablefmt="simple", disable_numparse=True) if table else "(keine Jobs)")

    # ------------------------------------------------------------ warnings / health
    notes = []
    if missing:
        notes.append("Config nicht (mehr) vorhanden, Jobs nicht berücksichtigt: " + ", ".join(missing))
    if unsupported:
        notes.append("Vom Solver nicht unterstützt (werden nicht laufen): " + ", ".join(unsupported))
    if never_started:
        notes.append("Nie gestartet (Task nicht unterstützt oder Job abgebrochen): "
                     + ", ".join(f"{j['solver']} / {j['benchmark']} / {j['task']}" for j in never_started))
    if finished:
        incomplete = [j for j in jobs if j["done"] < j["expected"]]
        for job in incomplete:
            notes.append(f"Unvollständig: {job['solver']} / {job['benchmark']} / {job['task']} ({job['done']}/{job['expected']})")
    else:
        for job in jobs:
            if job["status"] == "läuft" and job["last_result"] and now.timestamp() - job["last_result"] > timeout + 120:
                notes.append(
                    f"Seit {fmt_duration(now.timestamp() - job['last_result'])} keine neue Instanz: "
                    f"{job['solver']} / {job['benchmark']} / {job['task']} (mehr als Timeout - hängt der Job?)"
                )
        solver_configs = [load_group_config("solver", c) for c in sweep_values(sweep_params(cfg).get("solver"))]
        solver_dirs = {os.path.dirname(c["path"]) for c in solver_configs if c}
        active = 0
        for proc in psutil.process_iter(attrs=["cmdline"]):
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if any(d and d in cmdline for d in solver_dirs) and "progress.py" not in cmdline:
                active += 1
        notes.append(f"Aktive Solver-Prozesse auf diesem Rechner: {active}")
    if notes:
        out.append("")
        out.extend(notes)

    print("\n".join(out))


if __name__ == "__main__":
    main()
