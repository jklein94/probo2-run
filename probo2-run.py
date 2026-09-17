import hydra
from omegaconf import DictConfig
from src import solver_interfaces
from src import utils, config_validater
from hydra.core.utils import JobReturn
from typing import Any, List
from hydra.experimental.callback import Callback

from hydra.core.hydra_config import HydraConfig
from hydra.utils import get_original_cwd
from pathlib import Path

import os

import tqdm


def run_solver_dynamic_accaptance(cfg: DictConfig) -> None:
    pass


def run_solver_dynamic_enumeration(cfg: DictConfig) -> None:
    pass


def run_solver_static_accaptance(cfg: DictConfig) -> None:
    """
    Runs a solver with static acceptance criteria based on the provided configuration.

    Args:
        cfg (DictConfig): Configuration object containing solver, benchmark, and other settings.

    Returns:
        None

    The function performs the following steps:
    1. Retrieves Hydra configuration and sets up output directories.
    2. Dumps the current configuration to a file.
    3. Determines the matching format between solver and benchmark.
    4. Retrieves instances and query argument instances based on the benchmark path and formats.
    5. Builds an in-memory mapping from instance names to query arguments.
    7. Constructs the solver interface command based on the configuration.
    8. Adjusts the solver command to include the instance file and query arguments.
    9. Runs the solver for each instance with a timeout and captures the output.
    10. Validates the solver output and appends additional information.
    11. Writes the results to a CSV file.

    Note:
        The function uses various utility functions from the `utils` module to perform tasks such as dumping configurations,
        retrieving files, running the solver, validating output, and writing results.
    """

    hydra_config = HydraConfig.get()
    run_dir = hydra_config.runtime.output_dir
    output_root_dir = os.path.join(run_dir, hydra_config.output_subdir)

    utils.dump_configs(cfg)

    matching_format = utils.get_matching_format(cfg.solver.format, cfg.benchmark.format)

    if matching_format is None:
        print(
            f"No matching formats for {cfg.solver.format=} and {cfg.benchmark.format=}"
        )
        return None

    instances = utils.get_files_with_extension(cfg.benchmark.path, matching_format)

    query_argument_instances = utils.get_files_with_extension(
        cfg.benchmark.path, cfg.benchmark.query_arg_format
    )

    # Generate mapping from the instances name (without extension) to the query argument
    try:
        instance_to_query_arg_mapping = utils.generate_instance_to_query_arg_mapping(
            instances, query_argument_instances, cfg.benchmark.query_arg_format
        )
    except ValueError as e:
        print(e)
        print("Please make sure the query argument files are present for all instances.")
        return None

    solver_interface_command = solver_interfaces.interfaces_dict[cfg.solver.interface](
        cfg
    )

    # Get the indicies of the options that change from solver call to solver call
    if cfg.solver.interface == "legacy":
        index_file_format_flag = solver_interface_command.index("-fo")
        solver_interface_command[index_file_format_flag + 1] = matching_format

    # Insert the file after '-f' flag
    index_option_to_change = solver_interface_command.index("-f") + 1

    desc = f"{cfg.solver.name}"

    # Check if the solver is run with additional paramters, if so, append them to the result file name
    solver_output_file_name = utils.get_solver_output_file_name(cfg)

    result_file_path = os.path.join(output_root_dir, solver_output_file_name)

    utils.write_result_file_to_index(result_file_path, index_file=cfg.result_index_file)

    # Instances already logged in result_file_path are skipped so re-running a job
    # does not append duplicate rows for the same result_path
    completed_result_paths = utils.get_completed_result_paths(result_file_path)

    if cfg.run_subset is not False:
        instances = utils.get_instances_subset(instances, cfg)

    for instance in tqdm.tqdm(instances, desc=desc):

        # Set instance
        solver_interface_command[index_option_to_change] = instance
        instance_name = Path(instance).stem
        query_arg_command = ["-a", instance_to_query_arg_mapping[instance_name]]

        final_solver_interface_command = solver_interface_command + query_arg_command
        # solver_interface_command.extend(query_arg_command)
        output_file_name = f"{instance_name}.out"
        # Check if current_output_file_path exists
        if os.path.exists(os.path.join(output_root_dir, output_file_name)):
            # Check if we run a solver with paramters
            if "argument" in cfg.solver:
                # Check if the arguments are present in the experiment sweep params
                for param in cfg.solver.argument:
                    if param in cfg:
                        output_file_name += f"_{param}_{cfg[param]}"

        current_output_file_path = os.path.join(output_root_dir, output_file_name)

        if current_output_file_path in completed_result_paths:
            continue

        result = utils.run_solver_with_timeout(
            final_solver_interface_command,
            cfg.timeout,
            current_output_file_path,
            solver_path=cfg.solver.path,
            memory_limit_mb=cfg.solver_memory_limit_mb,
        )

        # Validate solver output
        is_output_valid = utils.validate_solver_output_accaptance_task(cfg, result)
        result.update({"solver_output_valid": is_output_valid})

        # Update the runtimes of the solver to the timeout value if the output is invalid
        if not is_output_valid:
            result["user_sys_time"] = cfg.timeout
            result["perfcounter_time"] = cfg.timeout

        # Append additional info like solver, benchmark and general infos
        prefixed_solver_info = utils.generate_solver_info(cfg)

        # prefixed_benchmark_info
        prefixed_benchmark_info = utils.add_prefix_to_dict_keys(
            cfg.benchmark, "benchmark_"
        )
        result.update(prefixed_solver_info)
        result.update(prefixed_benchmark_info)
        result.update(
            {
                "experiment_name": cfg.name,
                "run": cfg.runs,
                "task": cfg.task,
                "timeout": cfg.timeout,
                "instance": instance,
            }
        )

        # Write results to file
        utils.write_result_to_csv(data_dict=result, path=result_file_path)


# Method to run static enumeration task such as SE or EE
def run_solver_static_enumeration(cfg: DictConfig) -> None:
    """
    Executes a static enumeration solver based on the provided configuration.

    Args:
        cfg (DictConfig): Configuration object containing solver and benchmark settings.

    The function performs the following steps:
    1. Dumps the configuration settings.
    2. Determines the matching format between solver and benchmark.
    3. Retrieves the list of benchmark instances.
    4. Prepares the solver interface command.
    5. Adjusts the solver command based on the interface type.
    6. Sets up the output directory and result file path.
    7. Iterates over each benchmark instance, runs the solver, validates the output, and writes the results to a CSV file.

    The function exits if no matching formats are found between the solver and benchmark.
    """

    utils.dump_configs(cfg)

    matching_format = utils.get_matching_format(cfg.solver.format, cfg.benchmark.format)

    if matching_format is None:
        print(
            f"No matching formats for {cfg.solver.format=} and {cfg.benchmark.format=}"
        )
        exit()

    instances = utils.get_files_with_extension(cfg.benchmark.path, matching_format)

    solver_interface_command = solver_interfaces.interfaces_dict[cfg.solver.interface](
        cfg
    )

    # Get the indicies of the options that change from solver call to solver call
    if cfg.solver.interface == "legacy":
        index_file_format_flag = solver_interface_command.index("-fo")
        solver_interface_command[index_file_format_flag + 1] = matching_format

    # Insert the file after '-f' flag
    # This is the only thing that changes from call to call for a solver
    index_option_to_change = solver_interface_command.index("-f") + 1

    desc = f"{cfg.solver.name}"

    hydra_config = HydraConfig.get()

    run_dir = hydra_config.runtime.output_dir
    output_root_dir = os.path.join(run_dir, hydra_config.output_subdir)

    # Check if the solver is run with additional paramters, if so, append them to the result file name
    solver_output_file_name = utils.get_solver_output_file_name(cfg)

    result_file_path = os.path.join(output_root_dir, solver_output_file_name)

    utils.write_result_file_to_index(result_file_path, index_file=cfg.result_index_file)

    # Instances already logged in result_file_path are skipped so re-running a job
    # does not append duplicate rows for the same result_path
    completed_result_paths = utils.get_completed_result_paths(result_file_path)

    if cfg.run_subset is not False:
        instances = utils.get_instances_subset(instances, cfg)

    for instance in tqdm.tqdm(instances, desc=desc):

        # Set instance
        solver_interface_command[index_option_to_change] = instance
        instance_name = Path(instance).stem

        output_file_name = f"{instance_name}.out"
        # Check if current_output_file_path exists
        if os.path.exists(os.path.join(output_root_dir, output_file_name)):
            # Check if we run a solver with paramters
            if "argument" in cfg.solver:
                # Check if the arguments are present in the experiment sweep params
                for param in cfg.solver.argument:
                    if param in cfg:
                        output_file_name += f"_{param}_{cfg[param]}"

        current_output_file_path = os.path.join(output_root_dir, output_file_name)

        if current_output_file_path in completed_result_paths:
            continue

        result = utils.run_solver_with_timeout(
            solver_interface_command,
            cfg.timeout,
            current_output_file_path,
            solver_path=cfg.solver.path,
            memory_limit_mb=cfg.solver_memory_limit_mb,
        )

        # Validate solver output
        is_output_valid = utils.validate_solver_output_enumeration_task(cfg, result)
        result.update({"solver_output_valid": is_output_valid})

        # Update the runtimes of the solver to the timeout value if the output is invalid
        if not is_output_valid:
            result["user_sys_time"] = cfg.timeout
            result["perfcounter_time"] = cfg.timeout

        # Append additional info like solver, benchmark and general infos
        prefixed_solver_info = utils.generate_solver_info(cfg)

        # prefixed_benchmark_info
        prefixed_benchmark_info = utils.add_prefix_to_dict_keys(
            cfg.benchmark, "benchmark_"
        )
        result.update(prefixed_solver_info)
        result.update(prefixed_benchmark_info)
        result.update(
            {
                "experiment_name": cfg.name,
                "run": cfg.runs,
                "task": cfg.task,
                "timeout": cfg.timeout,
                "instance": instance,
            }
        )

        # Write results to file
        utils.write_result_to_csv(data_dict=result, path=result_file_path)


@hydra.main(version_base=None, config_path="configs", config_name="config")
def run_experiment(cfg: DictConfig) -> None:
    # Generate custom directories
    os.makedirs(cfg.evaluation_output_dir, exist_ok=True)

    # Change the format string to a list
    if isinstance(cfg.benchmark.format, str):
        cfg.benchmark.format = [cfg.benchmark.format]  # Wrap single string in a list

    if cfg.config_validation.validate_config:
        # check if the root directory

        config_valid = config_validater.validate_config(cfg)
        if not config_valid:
            print("Experiment aborted due to bad config.")
            print(
                "You can deactivate the config validater by setting validate_config: False in the config.yaml"
            )
            return
        print("Config is valid. Start running experiment.")
    # Run experiment based on task or config
    # Check if the cfg.task string contains the prefix SE or EE

    if not utils.task_allowed_for_solver(cfg, cfg.task):
        print("\n" + "-"*60)
        print(f"Skipping: task '{cfg.task}' is not in the allowed task list for solver '{cfg.solver.name}' (solver_task_mapping).")
        print("-"*60 + "\n")
        return

    if utils.solver_supports_task(cfg.solver.path, cfg.task):

        if cfg.task.startswith("SE") or cfg.task.startswith("EE"):
            run_solver_static_enumeration(cfg)
        # Check if the cfg.task string contains the prefix DC or DS
        elif cfg.task.startswith("DC") or cfg.task.startswith("DS"):
            run_solver_static_accaptance(cfg)
    else:
        print("\n" + "="*60)
        print(f"⚠️  WARNING: Solver '{cfg.solver.path}' does NOT support task '{cfg.task}'.")
        print("Aborting experiment.")
        print("="*60 + "\n")
        return

if __name__ == "__main__":
    run_experiment()
