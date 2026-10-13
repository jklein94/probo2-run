from pathlib import Path
from typing import List, Dict

import subprocess
import time
import os
import signal
import resource
import fcntl
from omegaconf import DictConfig, OmegaConf
from hydra.core.hydra_config import HydraConfig

import csv
import os
import pandas as pd
import psutil

def solver_supports_task(solver_path: str, task: str) -> bool:
    """
    Calls the solver with the "--problems" argument and checks if the output contains
    the specified task string. The solver can be an executable binary, a shell script (.sh),
    or a Python script (.py).

    Args:
        solver_path (str): The full path to the solver.
        task (str): The task string to search for in the solver's output.

    Returns:
        bool: True if the task string is found in the output, False otherwise.
    """
    # Determine the command based on the file extension
    _, ext = os.path.splitext(solver_path)
    ext = ext.lower()
    problems_propmpt = "--problems"
    #problems_propmpt = "--problem" # needed for argmat solvers from ICCMA17

    if ext == ".py":
        # Use the Python interpreter to run the script
        command = ["python", solver_path, problems_propmpt]
    elif ext == ".sh":
        # Use bash to run shell scripts
        command = ["bash", solver_path, problems_propmpt]
    else:
        # Assume it's an executable binary
        command = [solver_path, problems_propmpt]

    # Get the parent directory of the solver
    parent_dir = os.path.dirname(solver_path)

    try:
        # Run the solver command in the parent directory and capture output
        result = subprocess.run(
            command,
            cwd=parent_dir,        # <-- Change working directory
            capture_output=True,
            text=True,
            check=True
        )
        # Check if the task string is present in the output
        return task in result.stdout

    except subprocess.CalledProcessError as e:
        # The solver call failed; log the error and return False
        print(f"Error running solver: {e}")
        return False
    except FileNotFoundError as e:
        # The solver file was not found or is not accessible
        print(f"Solver not found: {e}")
        return False


def _as_str_list(value) -> list:
    """
    Normalizes a task/benchmark specification to a list of stripped strings.
    Accepts a single string (optionally comma separated, e.g. "SE-PR, SE-CO") or a list.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    result = []
    for v in value:
        result.extend(_as_str_list(v))
    return result


def _current_benchmark_identifiers(cfg: DictConfig) -> set:
    """
    Returns all identifiers the current benchmark can be referred to in
    `solver_task_mapping`: its `name` field (e.g. ICCMA25_legacy) and the Hydra
    config-group choice (e.g. I25_legacy or /I25_legacy), if available.
    """
    identifiers = {str(cfg.benchmark.name)}
    try:
        choice = HydraConfig.get().runtime.choices.get("benchmark")
        if choice:
            identifiers.add(str(choice))
            identifiers.add(str(choice).lstrip("/"))
    except Exception:
        # HydraConfig not initialized (e.g. when called outside of a Hydra run)
        pass
    return identifiers


def task_allowed_for_solver(cfg: DictConfig, task: str) -> bool:
    """
    Checks whether the given task is allowed for the current solver (and benchmark)
    according to the optional `cfg.solver_task_mapping` config.

    `solver_task_mapping` is an opt-in dict keyed by solver name (cfg.solver.name).
    Two value formats are supported per solver:

    1. A list of task strings - the solver is restricted to these tasks on every
       swept benchmark (original behavior):

           solver_task_mapping:
             fudge_23: [SE-PR, SE-CO]

    2. A list of benchmark entries - the solver only runs the listed tasks on the
       listed benchmark; benchmarks not listed are skipped entirely for this solver:

           solver_task_mapping:
             fudge_23:
               - benchmark: I23_apx_tgf      # config-group name or benchmark `name`
                 tasks: [SE-PR, SE-CO]       # `task` is accepted as alias
               - benchmark: I25_legacy
                 tasks: DC-CO, DS-CO         # comma separated string also works

       `benchmark` may also be a list of benchmarks. An entry without `tasks`
       allows all swept tasks on that benchmark.

    A solver name that is not present as a key in the mapping is unrestricted and
    runs on all swept benchmark/task combinations. If `solver_task_mapping` is
    absent or empty, every combination is allowed.

    Args:
        cfg (DictConfig): The full run configuration, optionally containing a
            `solver_task_mapping` dict and always containing `cfg.solver.name`.
        task (str): The task string to check (typically cfg.task).

    Returns:
        bool: True if the combination of cfg.solver.name, the current benchmark and
              task is allowed, False otherwise.
    """
    mapping = cfg.get("solver_task_mapping", None)
    if not mapping:
        return True

    solver_name = cfg.solver.name
    if solver_name not in mapping:
        return True

    spec = mapping[solver_name]
    if spec is None:
        return True
    if isinstance(spec, str):
        return task in _as_str_list(spec)

    entries = list(spec)
    if not any(isinstance(e, (dict, DictConfig)) for e in entries):
        # Format 1: plain list of tasks
        return task in _as_str_list(entries)

    # Format 2: list of {benchmark, tasks} entries
    benchmark_ids = _current_benchmark_identifiers(cfg)
    for entry in entries:
        if not isinstance(entry, (dict, DictConfig)):
            raise ValueError(
                f"solver_task_mapping['{solver_name}']: mixing plain tasks and benchmark "
                f"entries is not supported (got {entry!r})."
            )
        if "benchmark" not in entry:
            raise ValueError(
                f"solver_task_mapping['{solver_name}']: entry {dict(entry)} has no 'benchmark' key."
            )
        entry_benchmarks = {b.lstrip("/") for b in _as_str_list(entry["benchmark"])}
        if not entry_benchmarks & {b.lstrip("/") for b in benchmark_ids}:
            continue
        tasks = entry.get("tasks", entry.get("task", None))
        if tasks is None:
            return True
        if task in _as_str_list(tasks):
            return True
    return False


def record_skipped_combination(cfg: DictConfig, reason: str = "solver_task_mapping") -> str:
    """
    Appends the current (solver, benchmark, task) combination to
    `cfg.skipped_combinations_file`, so intentionally skipped combinations can be
    distinguished from missing results (e.g. crashed jobs) after the experiment.

    The file is shared by all jobs of a sweep, so writes are serialized with an
    exclusive file lock (safe for parallel launchers such as joblib).

    Returns:
        str: The path of the skipped-combinations file.
    """
    path = cfg.skipped_combinations_file
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        benchmark_config = HydraConfig.get().runtime.choices.get("benchmark")
    except Exception:
        benchmark_config = None
    row = {
        "experiment_name": cfg.name,
        "solver_name": cfg.solver.name,
        "solver_version": cfg.solver.get("version", None),
        "benchmark_name": cfg.benchmark.name,
        "benchmark_config": benchmark_config,
        "task": cfg.task,
        "run": cfg.runs,
        "reason": reason,
    }
    with open(path, "a", newline="", encoding="utf-8") as csvfile:
        fcntl.flock(csvfile, fcntl.LOCK_EX)
        try:
            writer = csv.DictWriter(csvfile, fieldnames=row.keys())
            # Decide on the header while holding the lock to avoid duplicate headers
            if os.fstat(csvfile.fileno()).st_size == 0:
                writer.writeheader()
            writer.writerow(row)
            csvfile.flush()
        finally:
            fcntl.flock(csvfile, fcntl.LOCK_UN)
    return path


def write_result_to_csv(path, data_dict):
    """
    Writes a dictionary to a CSV file at the specified path.

    If the file already exists, the dictionary is appended to it.
    If the file does not exist, it is created, and the dictionary is added.

    Parameters:
    - path (str): The file path of the CSV file.
    - data_dict (dict): The dictionary to write to the CSV file.

    Note:
    The CSV file will have columns corresponding to the keys of the dictionary.
    Ensure that all dictionaries written to the file have the same keys for consistency.
    """
    file_exists = os.path.isfile(path)
    write_header = True
    if file_exists and os.path.getsize(path) > 0:
        write_header = False

    with open(path, 'a', newline='', encoding='utf-8') as csvfile:
        fieldnames = data_dict.keys()
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(data_dict)



def get_completed_result_paths(result_file_path: str) -> set:
    """
    Returns the set of `result_path` values that already have a row recorded in the
    given results CSV, so a run can skip instances that were already completed
    instead of appending a duplicate row for the same result_path.

    Args:
        result_file_path (str): Path to the solver's results.csv file.

    Returns:
        set: The set of result_path values already present in the file (empty if the
             file does not exist yet).
    """
    if not os.path.isfile(result_file_path):
        return set()

    with open(result_file_path, "r", newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        return {row["result_path"] for row in reader}


def _preexec_with_memory_limit(memory_limit_mb):
    """Build a preexec_fn that starts a new session and, if given, caps the
    child's virtual address space (RLIMIT_AS) so an over-allocating solver
    fails on its own instead of triggering the system/cgroup OOM killer."""
    def _apply():
        os.setsid()  # Start in a new process group (Linux/macOS)
        if memory_limit_mb is not None:
            limit_bytes = int(memory_limit_mb) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
    return _apply


def run_solver_with_timeout(command, timeout, output_file, time_flag=True, solver_path=None, memory_limit_mb=None):

    if solver_path is None:
        solver_path = os.getcwd()
    else:
        # get parent of solver executable
        solver_path = os.path.dirname(solver_path)

    if time_flag:
        command = ["time", "-p"] + command  # Use `-p` for a more parsable format

    result = {
        "result_path": output_file,
        "perfcounter_time": None,
        "user_sys_time": None,
        "timed_out": False,
        "exit_with_error": False,
        "error_code": None,
    }

    try:
        # Start the process with a new process group
        start_perf_time = time.perf_counter()  # Measure time with perfcounter

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=_preexec_with_memory_limit(memory_limit_mb),
            cwd=solver_path
        )
        # Wait for the process to complete or timeout
        stdout, stderr = process.communicate(timeout=timeout)
        end_perf_time = time.perf_counter()
        result["perfcounter_time"] = end_perf_time - start_perf_time

        # Parse the `time` command output if time_flag is true
        if time_flag:
            try:
                # Extract real time from `stderr` (output of `time` command)
                time_output = stderr.strip().split("\n")
                time_values = {}
                for line in time_output:
                    if line.startswith("real"):
                        time_values["real"] = float(line.split()[1])
                    elif line.startswith("user"):
                        time_values["user"] = float(line.split()[1])
                    elif line.startswith("sys"):
                        time_values["sys"] = float(line.split()[1])
                user_sys_time = time_values["user"] + time_values["sys"]
                result["user_sys_time"] = user_sys_time
            except Exception as e:
                print("Failed to parse time output:", e)
                result["exit_with_error"] = True
                result["error_code"] = e
                result["user_sys_time"] = timeout
                result["perfcounter_time"] = timeout

        # Write solver output to file
        with open(output_file, "w") as file:
            file.write(stdout)
            #file.write('NO\nw 1 3 4')

        # Set exit status and error code, unless a `time` output parsing failure
        # above already flagged this result as an error
        if not result["exit_with_error"]:
            result["exit_with_error"] = process.returncode != 0
            result["error_code"] = process.returncode if process.returncode != 0 else None

        # TODO: Set timeout when solver does not return 0 as return value

    except subprocess.TimeoutExpired:
        result["timed_out"] = True
        result["user_sys_time"] = timeout
        result["perfcounter_time"] = timeout

        # Ensure no stale output from a previous run at this path is left behind
        with open(output_file, "w") as file:
            file.write("")

        try:
            # Use psutil to get the parent process and all its children (recursively)
            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
            # Kill each child process
            for child in children:
                child.kill()
            # Optionally wait for the child processes to terminate
            psutil.wait_procs(children, timeout=5)
        except Exception as e:
            # Log or handle the exception if needed
            print(f"Error killing child processes: {e}")

        try:
            # Kill the process group to ensure the main process is terminated
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except Exception as e:
            # Log or handle if process group killing fails
            print(f"Error killing process group: {e}")

    except Exception as e:
        with open(output_file, "w") as file:
            file.write(str(e))
        result["exit_with_error"] = True
        result["error_code"] = e
        result["user_sys_time"] = timeout
        result["perfcounter_time"] = timeout
    return result


def get_solver_output_file_name(cfg: DictConfig) -> str:
    """
    Generates a result file name based on the configuration provided.

    Args:
        cfg (DictConfig): A configuration object that contains solver parameters.

    Returns:
        str: The generated result file name. If 'argument' is present in cfg.solver,
             the file name will include the arguments and their values from the configuration.
             Otherwise, it defaults to 'results.csv'.
    """
    if 'argument' in cfg.solver:
        # Check if the arguments are present in the experiment sweep params
        result_file_name = 'results'
        for param in cfg.solver.argument:
            if param in cfg:
                result_file_name += f"_{param}_{cfg[param]}"
        result_file_name += '.csv'
    else:
        result_file_name = 'results.csv'

    return result_file_name


def add_prefix_to_dict_keys(original_dict, prefix):
    """
    Returns a new dictionary with the specified prefix added to each key.

    Parameters:
    - original_dict (dict): The original dictionary whose keys you want to prefix.
    - prefix (str): The prefix string to add to each key.

    Returns:
    - dict: A new dictionary with prefixed keys.
    """
    return {f"{prefix}{key}": value for key, value in original_dict.items()}

def generate_solver_info(cfg: DictConfig ) -> dict:
    solver_info = cfg.solver.copy()
    if 'argument' in cfg.solver:
        # Check if the arguments are present in the experiment sweep params
        for param in cfg.solver.argument:
            if param in cfg:
                solver_info['name'] += f"_{param}_{cfg[param]}"

    return add_prefix_to_dict_keys(solver_info,'solver_')


def get_instances_subset(instances: List, cfg: DictConfig) -> List:
    # Check if cfg.run_subset is a integer:
    if isinstance(cfg.run_subset, int):
        console.print(f"[yellow]Note: Experiment {cfg.name} is executed with a subset of the first {cfg.run_subset} instances of {cfg.benchmark.name} [/yellow]")
        instances = instances[:cfg.run_subset]
    # Check if run_subset a path
    elif os.path.isfile(cfg.run_subset):
        with open(cfg.run_subset, 'r') as file:
            subset_instances = file.read().splitlines()
        instances = [instance for instance in instances if Path(instance).stem in subset_instances]
        console.print(f"[yellow]Note: Experiment {cfg.name} is executed with a subset of instances of benchmark {cfg.benchmark.name} from the file {cfg.run_subset}[/yellow]")

    return instances


def write_result_file_to_index(filepath, index_file="result_file_index.txt"):
    """
    Writes a file path to 'file_index.txt'. Creates the file if it doesn't exist,
    and appends to it if it already exists.

    Args:
        filepath (str): The file path to write.
        index_file (str): The name of the index file (default is 'file_index.txt').
    """
    try:
        with open(index_file, "a") as file:  # Open in append mode
            file.write(filepath + "\n")  # Append the file path followed by a newline
        #print(f"File path '{filepath}' added to '{index_file}'.")
    except Exception as e:
        print(f"An error occurred: {e}")

def write_evaluation_file_to_index(filepath, index_file="evaluation_result_file_index.txt"):
    """
    Writes a file path to 'file_index.txt'. Creates the file if it doesn't exist,
    and appends to it if it already exists.

    Args:
        filepath (str): The file path to write.
        index_file (str): The name of the index file (default is 'file_index.txt').
    """
    try:
        with open(index_file, "a") as file:  # Open in append mode
            file.write(filepath + "\n")  # Append the file path followed by a newline
        #print(f"File path '{filepath}' added to '{index_file}'.")
    except Exception as e:
        print(f"An error occurred: {e}")

def get_unique_dir_name(base_path):
    """
    Returns a unique directory name by adding a numbered suffix to the directory name
    if it already exists.

    Parameters:
    - base_path (str): The full path of the directory to check.

    Returns:
    - str: A unique directory path with a numbered suffix if needed.
    """
    # Get the directory and base name from the path
    dir_name, base_name = os.path.split(base_path)

    # If the base path does not exist, return it
    if not os.path.exists(base_path):
        return base_path

    # Start adding suffixes to find a unique name
    counter = 1
    while True:
        new_base_name = f"{base_name}_{counter}"
        new_path = os.path.join(dir_name, new_base_name)
        if not os.path.exists(new_path):
            return new_path
        counter += 1


def get_files_with_extension(directory: str, extension: str) -> List[str]:
    """
    Retrieves all files with a specified extension within a given directory.

    This function searches recursively within the specified directory and returns a list
    of file paths that match the given extension.

    Args:
        directory (str): The directory path to search within.
        extension (str): The file extension to filter by (e.g., 'txt', 'csv').

    Returns:
        List[str]: A list of file paths that have the specified extension.
    """
    return [
        str(file) for file in Path(directory).rglob(f"*.{extension}")
        if file.is_file()
    ]


def strip_extension(filename: str, extension: str) -> str:
    """
    Removes the specified extension from a filename.
    If the extension is not found, it removes all extensions.
    """
    if filename.endswith(extension):
        return filename[: -len(extension) - 1] # Remove the extension and the dot
    return os.path.splitext(filename)[0]

def generate_instance_to_query_arg_mapping(instances: List[str], query_argument_instances: List[str], extension: str) -> Dict[str, str]:
    """
    Maps instance names (without extension) to the content of corresponding query argument instances,
    splitting query_argument_instances on the specified extension.

    :param instances: List of file paths to instance files.
    :param query_argument_instances: List of file paths to query argument instance files.
    :param extension: Extension to split query argument instances on (e.g., '.arg').
    :return: Dictionary mapping instance names to query argument contents.
    """
    instance_names = {strip_extension(os.path.basename(path), extension): path for path in instances}
    query_arg_names = {strip_extension(os.path.basename(path), extension): path for path in query_argument_instances}

    if set(instance_names.keys()) != set(query_arg_names.keys()):
            # Compute mismatched subsets
        instance_only = set(instance_names.keys()) - set(query_arg_names.keys())
        query_only = set(query_arg_names.keys()) - set(instance_names.keys())

        # Print instance files that do not match any query arguments
        if instance_only:
            print("Instance files not found in query arguments:")
            for key in instance_only:
                print(f"  - {key}")

        # Print query arguments that do not match any instance files
        if query_only:
            print("Query arguments not found in instance files:")
            for key in query_only:
                print(f"  - {key}")

        raise ValueError("Mismatch between instance files and query argument files.")

    mapping = {}

    for name, instance_path in instance_names.items():
        query_arg_path = query_arg_names[name]
        with open(query_arg_path, 'r') as f:
            query_arg_content = f.read().strip()

        mapping[name] = query_arg_content

    return mapping


def get_matching_format(solver_formats, benchmark_formats):
    """
    Determines the first matching format between two lists of formats: one from the solver and one from the benchmark.

    This method compares two input arguments, `solver_formats` and `benchmark_formats`,which can either be a single string or a list of strings.
    It returns the first common format between the two sets. If no match is found, it returns `None`.

    Args:
        solver_formats (str | list of str): A single format string or a list of format strings used by the solver.
        benchmark_formats (str | list of str): A single format string or a list of format strings used by the benchmark.

    Returns:
        str | None: The first matching format found between the two sets, or `None` if no common format exists.

    Example:
        >>> get_matching_format(['pdf', 'txt'], ['txt', 'csv'])
        'txt'

        >>> get_matching_format('pdf', ['txt', 'csv'])
        None

    Notes:
        - If either `solver_formats` or `benchmark_formats` is a single string, it is converted to a list for comparison.
        - The method uses set intersection to find shared formats, ensuring that the matching format is selected from the intersection of both input sets.
    """
    if isinstance(solver_formats, str):
        solver_formats = [solver_formats]
    if isinstance(benchmark_formats, str):
        benchmark_formats = [benchmark_formats]
    _shared = list(set.intersection(set(solver_formats), set(benchmark_formats)))

    if _shared:
        return _shared[0]
    else:
        return None



def is_solver_output_valid_accaptance_task(output_file:str) -> bool:
    """
    Checks if the output file contains the expected output for the acceptance task.

    Args:
        output_file (str): The path to the output file generated by the solver.

    Returns:
        bool: True if the output is valid, False otherwise.
    """

    with open(output_file, 'r') as f:
        lines = f.readlines()

    # We only check if the first line contains the String YES or NO
    if len(lines) == 0:
        return False

    if "YES" in lines[0] or "NO" in lines[0]:
        return True

    return False


def is_valid_solver_output_enumeration_task(interface: str, task: str, solver_output_path: str) -> bool:
    """
    Validate solver output for SE or EE tasks under the ICCMA23 or ICCMA15-21 format.

    :param interface:   The interface name, e.g., "ICCMA23" or something in ["ICCMA15","ICCMA21", ...].
    :param task:        The task, e.g., "SE" (stable extension) or "EE" (all extensions).
    :param solver_output: The raw output string from the solver.

    :return: True if the output is valid for the given interface/task specification, False otherwise.

    ------------------------------------------------------------
    FORMATTING RULES

    1) ICCMA23
       - SE task:
           • If there is a solution: a single line beginning with "_w" followed by space-separated integers
             e.g. "_w 1 2 4 5"
           • If there is no solution: the single line "NO"
       - EE task:
           • Not specified in the question. You may adapt to your needs.
             Below, we mark anything as valid for EE to avoid throwing false negatives.

    2) ICCMA15–21 (legacy interfaces)
       - SE task:
           • A single extension enclosed in brackets, e.g. "[1,2,3]" or "[]".
             (In practice, stable extension solvers might return "[]", or "[1,2,5]" etc.)
       - EE task:
           • "[]" if there is no extension.
           • "[ [] ]" if there is only the empty extension.
           • "[ [1,2,3],[2,4,5] ]" if there are multiple extensions.
             In short, check either for "[]" or something that starts with "[[" and ends with "]]".
    ------------------------------------------------------------
    """
    with open(solver_output_path, 'r') as f:
        solver_output = f.read()
    # Clean up any leading/trailing whitespace
    output = solver_output.strip()
    is_valid = True

    # Normalize the interface string for comparison
    if interface.lower() == "legacy":
        # Legacy interface checks
        if "SE-" in task:
            # Expect something like "[...]" or possibly "[]" if empty; "NO" is also valid
            if output == "NO":
                is_valid = True
            elif output.startswith("[") and output.endswith("]"):
                is_valid = True
            else:
                is_valid = False

        elif "EE-" in task:
            # Check for [] or something in the style [[ ... ]]
            if output == "[]":
                # No extension scenario
                is_valid = True
            elif output.startswith("[[") and output.endswith("]]"):
                # Extensions enclosed in double brackets
                is_valid = True
            else:
                is_valid = False
        else:
            # Unknown task
            is_valid = False

    elif interface.lower() == "i23":
        # ICCMA23 checks
        if "SE-" in task:
            normalized_output = output.strip()

            # "NO" if no solution
            if normalized_output == "NO":
                is_valid = True
            else:
                parts = normalized_output.split()

                # Accept:
                #   w          -> empty extension
                #   w 1 2 3    -> extension containing integers
                if not parts or parts[0] != "w":
                    is_valid = False
                else:
                    try:
                        # For an empty extension, parts[1:] is empty and valid.
                        for part in parts[1:]:
                            int(part)

                        is_valid = True
                    except ValueError:
                        is_valid = False

        elif  "EE-" in task:
            # Not specified in the problem description for ICCMA23
            # If you have no specification, either allow or disallow by default.
            # Here, we'll allow anything for demonstration.
            is_valid = True
        else:
            is_valid = False
    else:
        # Unrecognized interface
        is_valid = False

    return is_valid


def validate_solver_output_enumeration_task(cfg: DictConfig, result: Dict[str, any]) -> bool:
    """
    Check the solver output and update the result dictionary with the validity of the solver output.

    Args:
        cfg: Configuration object containing solver and task information.
        result: Dictionary containing the result information including 'timed_out' and 'exit_with_error' keys.

    Returns:
        bool: Status of validity.
    """
    if cfg.check_solver_output:
        # If the solver did not time out or exit with an error, check if the output is valid
        if not result['timed_out'] and not result['exit_with_error']:
            # Check if the output is valid
            is_output_valid = is_valid_solver_output_enumeration_task(cfg.solver.interface, cfg.task, result['result_path'])
            return is_output_valid
        else:
            return False
    else:
        if  result['timed_out'] or result['exit_with_error']:
            return False
        else:
            return True
def validate_solver_output_accaptance_task(cfg: DictConfig, result: Dict[str, any]) -> bool:
    """
    Check the solver output and update the result dictionary with the validity of the solver output.

    Args:
        cfg: Configuration object containing solver and task information.
        result: Dictionary containing the result information including 'timed_out' and 'exit_with_error' keys.

    Returns:
        bool: Status of validity.
    """
    if cfg.check_solver_output:
        # If the solver did not time out or exit with an error, check if the output is valid
        if not result['timed_out'] and not result['exit_with_error']:
            # Check if the output is valid
            is_output_valid = is_solver_output_valid_accaptance_task(result['result_path'])
            return is_output_valid
        else:
            return False
    else:
        if  result['timed_out'] or result['exit_with_error']:
            return False
        else:
            return True


def dump_configs(cfg):
    """
    Dumps the solver and benchmark configurations into separate directories as YAML files.

    Args:
        cfg: The configuration object containing `solver` and `benchmark` configurations.
            - `cfg.configs_output_dir` (str): The root directory to save the configuration files.
            - `cfg.solver` (DictConfig): The solver configuration.
            - `cfg.solver.name` (str): The name of the solver.
            - `cfg.benchmark` (DictConfig): The benchmark configuration.
            - `cfg.benchmark.name` (str): The name of the benchmark.

    Returns:
        None
    """
    # Create directory and dump solver config
    solver_config_dump = os.path.join(cfg.configs_output_dir, "solver_config")
    os.makedirs(solver_config_dump, exist_ok=True)
    solver_config_file_path = os.path.join(solver_config_dump, f'{cfg.solver.name}_config.yaml')

    if not os.path.exists(solver_config_file_path):
        OmegaConf.save(config=cfg.solver, f=solver_config_file_path)
        print(f"Solver config saved to {solver_config_file_path}")

    # Create directory and dump benchmark config
    benchmark_config_dump = os.path.join(cfg.configs_output_dir, "benchmark_config")
    os.makedirs(benchmark_config_dump, exist_ok=True)
    benchmark_config_file_path = os.path.join(benchmark_config_dump, f'{cfg.benchmark.name}_config.yaml')

    if not os.path.exists(benchmark_config_file_path):
        OmegaConf.save(config=cfg.benchmark, f=benchmark_config_file_path)
        print(f"Benchmark config saved to {benchmark_config_file_path}")

from rich.console import Console
from rich.text import Text
from rich.panel import Panel

console = Console()

def create_callback_chain(callback_dict: dict, current_callback: str) -> None:
    """
    Takes a dictionary of callbacks and the name of the 'current' callback,
    and prints a visually formatted string of callback names in reverse order,
    starting with the current callback and including every stage that follows.
    The current callback is highlighted in bold green, while the subsequent
    stages are shown in dim text.
    """
    # Reverse the dictionary keys (assumed to be in the pipeline order)
    reversed_keys = list(callback_dict.keys())[::-1]

    # Ensure that the current callback exists in the list
    if current_callback not in reversed_keys:
        raise ValueError(f"Current callback '{current_callback}' not found in callback_dict keys.")

    # Get the index of the current callback in the reversed list
    index_current_callback = reversed_keys.index(current_callback)

    # Build the chain representation: from the current stage to the end
    chain_parts = []
    for i, stage in enumerate(reversed_keys[index_current_callback:]):
        if i == 0:
            # Highlight the current stage in bold green
            chain_parts.append(f"[bold green]{stage}[/bold green]")
        else:
            # Subsequent stages are appended with an arrow in dim styling
            chain_parts.append(f"[dim]→ {stage}[/dim]")
    chain_str = " ".join(chain_parts)

    # Create the panel that shows the full evaluation pipeline overview
    footer_highlighted = Panel.fit(
        f"[cyan]Evaluation Pipeline: {chain_str}",
        border_style="dim"
    )

    # Create an additional footer message (if needed) indicating what's now running
    footer = f"[bold cyan] + Now running:[/bold cyan] [bold green]{current_callback}[/bold green] "

    # Print the panel and footer to the console
    console.print("")
    console.print(footer_highlighted)
    console.print(footer)
    console.print("")


from rich.table import Table
def print_dataframe_as_rich_table(df: pd.DataFrame, title: str = "DataFrame") -> None:
    """
    Prints the given pandas DataFrame as a styled table using the Rich library.

    Args:
        df (pd.DataFrame): The DataFrame to display.
        title (str): The title displayed at the top of the table.
    """
    # Create a table with a styled title and border
    table = Table(title=f"[bold cyan]{title}[/bold cyan]", border_style="dim")

    # Add columns to the table. Column headers are styled in bold magenta.
    for col in df.columns:
        table.add_column(str(col), style="bold magenta", no_wrap=False)

    # Add each row from the DataFrame to the table
    for _, row in df.iterrows():
        # Convert each value in the row to a string for display
        row_values = [str(value) for value in row]
        table.add_row(*row_values)

    # Print the table to the console
    console.print(table)

def print_grouped_dataframe_as_rich_table(
    df: pd.DataFrame,
    title: str = "DataFrame",
    grouping: str = None
) -> None:
    """
    Prints the given pandas DataFrame grouped by a specified column as a styled table using the Rich library.
    Inserts a dashed separator line between groups.
    """
    # Create a table with a styled title and a dim border
    table = Table(title=f"[bold cyan]{title}[/bold cyan]", border_style="dim")

    # Add columns to the table
    for col in df.columns:
        table.add_column(str(col), no_wrap=False)

    # Group the DataFrame by the specified column
    grouped = df.groupby(grouping)

    # Convert grouped object to a list so we can tell when we're on the last group
    grouped_list = list(grouped)
    num_groups = len(grouped_list)

    for i, (group_name, group_df) in enumerate(grouped_list, start=1):
        # Add the group's rows
        for _, row in group_df.iterrows():
            row_values = [str(value) for value in row]
            table.add_row(*row_values)

        # If this isn't the last group, add a dashed separator row
        if i < num_groups:
            # For each column, insert a small string of dashes
            dash_row = ["-" * 10 for _ in df.columns]
            table.add_row(*dash_row, style="dim")

    # Print the table
    console.print(table)