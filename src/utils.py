from pathlib import Path
from typing import List, Dict

import subprocess
import time
import os
import signal
from omegaconf import DictConfig, OmegaConf

import csv
import os

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



def get_index_mutable_interface_options(options: list) -> dict:
    """
    Creates a mapping from each option in the provided list to its index.

    Given a list of options, this function creates and returns a dictionary where the keys are the options
    from the list, and the values are the corresponding index positions of those options in the list.

    Args:
        options (list): A list of options to be indexed.

    Returns:
        dict: A dictionary where the keys are the options from the input list, and the values are their
              respective indices in the list.

    Example:
        >>> get_index_mutable_interface_options(['a', 'b', 'c'])
        {'a': 0, 'b': 1, 'c': 2}

    Notes:
        - The function assumes that the elements in `options` are hashable (can be used as dictionary keys).
        - If the list contains duplicate values, only the index of the first occurrence will be stored.
    """
    option_to_index_map = {}
    for option in options:
        option_to_index_map[options] = options.index(option) + 1  # plus one to get the next index where the value is inserted
    return option_to_index_map


def run_solver_with_timeout(command, timeout, output_file, time_flag=True):
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
            preexec_fn=os.setsid,  # Start in a new process group (Linux/macOS)
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

        # Write solver output to file
        with open(output_file, "w") as file:
            file.write(stdout)
            #file.write('NO\nw 1 3 4')

        # Set exit status and error code
        result["exit_with_error"] = process.returncode != 0
        result["error_code"] = process.returncode if process.returncode != 0 else None

    except subprocess.TimeoutExpired:
        # Timeout case: kill the process group
        os.killpg(
            os.getpgid(process.pid), signal.SIGTERM
        )  # Terminate the process group
        result["timed_out"] = True
        result["user_sys_time"] = timeout
        result["perfcounter_time"] = timeout

    except Exception as e:
        result["exit_with_error"] = True
        result["error_code"] = e
        result["user_sys_time"] = timeout
        result["perfcounter_time"] = timeout
    return result


def need_additional_arguments(task: str):
    if "DC-" in task or "DS-" in task:
        return True
    else:
        return False

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
    if 'parameters' in cfg.solver:
        # Check if the arguments are present in the experiment sweep params
        result_file_name = 'results'
        for param in cfg.solver.parameters:
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
    if 'parameters' in cfg.solver:
        # Check if the arguments are present in the experiment sweep params
        for param in cfg.solver.parameters:
            if param in cfg:
                solver_info['name'] += f"_{param}_{cfg[param]}"

    return add_prefix_to_dict_keys(solver_info,'solver_')




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


def prepare_instances(cfg: DictConfig) -> List[str]:
    """
    Prepares a list of file paths based on the configuration provided in `cfg`.

    This function retrieves files with a specific extension from a directory specified in the `cfg`.
    The extension used for filtering is determined by the `solver.format` in `cfg`. If `solver.format`
    is 'i23', it will use the `benchmark.format` as the file extension; otherwise, it uses `solver.format` directly.

    Args:
        cfg (DictConfig): Configuration object containing `solver` and `benchmark` attributes.
                          Expected fields include:
                          - `cfg.solver.format` (str): The format extension for the solver.
                          - `cfg.benchmark.path` (str): The directory path for the benchmark files.
                          - `cfg.benchmark.format` (str): The fallback format if `solver.format` is 'i23'.

    Returns:
        List[str]: A list of file paths matching the specified extension.
    """
    if cfg.solver.format == "i23":
        return get_files_with_extension(cfg.benchmark.path,
                                        cfg.benchmark.format)
    else:
        return get_files_with_extension(cfg.benchmark.path, cfg.solver.format)


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


def save_instance_to_query_arg_mapping(instances: List[str], query_argument_instances: List[str], cfg: DictConfig, mapping_file_path: str) -> None:
        """
        Generates and saves a mapping from instance names to query argument contents if the mapping file does not already exist.

        Args:
            instances (List[str]): List of file paths to instance files.
            query_argument_instances (List[str]): List of file paths to query argument instance files.
            cfg (DictConfig): Configuration object containing benchmark attributes.
            mapping_file_path (str): Path to save the mapping file.

        Returns:
            None
        """
        if not os.path.exists(mapping_file_path):
            try:
                instance_to_query_arg_mapping = generate_instance_to_query_arg_mapping(
                    instances, query_argument_instances, cfg.benchmark.query_arg_format)
            except ValueError as e:
                print(e)
                print("Please make sure the query argument files are present for all instances.")
                return None

            with open(mapping_file_path, 'w') as f:
                f.write(OmegaConf.to_yaml(instance_to_query_arg_mapping))
        else:
            print(f"Mapping file already exists at {mapping_file_path}.")


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

    print(f'{output=}')
    is_valid = True

    # Normalize the interface string for comparison
    if interface.lower() == "legacy":
        # Legacy interface checks
        if "SE-" in task:
            # Expect something like "[...]" or possibly "[]" if empty
            # Minimal check: must start with "[" and end with "]"
            if not (output.startswith("[") and output.endswith("]")):
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
        print('checking i23')
        # ICCMA23 checks
        if "SE-" in task:
            print('checking SE')
            # "NO" if no solution, or "_w " followed by integers if there is a solution
            if output == "NO":
                is_valid = True
            elif output.startswith("w "):
                # Check the parts after splitting on whitespace
                parts = output.split()
                if parts[0] != "w":
                    is_valid = False
                else:
                    # Ensure all subsequent parts are valid integers
                    for p in parts[1:]:
                        try:
                            int(p)
                        except ValueError:
                            is_valid = False
                            break
            else:
                # Not matching "NO" or "w N1 N2..."
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
            is_output_valid = is_solver_output_valid_accaptance_task(cfg.solver.interface, cfg.task, result['result_path'])
            return is_output_valid
        else:
            return False
    else:
        return True


def dump_configs(cfg):
    """
    Dumps the solver and benchmark configurations into separate directories as YAML files.

    Args:
        cfg: The configuration object containing `solver` and `benchmark` configurations.
            - `cfg.root_dir` (str): The root directory to save the configuration files.
            - `cfg.solver` (DictConfig): The solver configuration.
            - `cfg.solver.name` (str): The name of the solver.
            - `cfg.benchmark` (DictConfig): The benchmark configuration.
            - `cfg.benchmark.name` (str): The name of the benchmark.

    Returns:
        None
    """
    # Create directory and dump solver config
    solver_config_dump = os.path.join(cfg.root_dir, "solver_config")
    os.makedirs(solver_config_dump, exist_ok=True)
    solver_config_file_path = os.path.join(solver_config_dump, f'{cfg.solver.name}_config.yaml')

    if not os.path.exists(solver_config_file_path):
        OmegaConf.save(config=cfg.solver, f=solver_config_file_path)
        print(f"Solver config saved to {solver_config_file_path}")

    # Create directory and dump benchmark config
    benchmark_config_dump = os.path.join(cfg.root_dir, "benchmark_config")
    os.makedirs(benchmark_config_dump, exist_ok=True)
    benchmark_config_file_path = os.path.join(benchmark_config_dump, f'{cfg.benchmark.name}_config.yaml')

    if not os.path.exists(benchmark_config_file_path):
        OmegaConf.save(config=cfg.benchmark, f=benchmark_config_file_path)
        print(f"Benchmark config saved to {benchmark_config_file_path}")


