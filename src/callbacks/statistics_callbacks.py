import pandas as pd
from typing import Any
from hydra.experimental.callback import Callback
from omegaconf import DictConfig
import os
from src import utils
from functools import reduce
from hydra.core.hydra_config import HydraConfig
from rich.console import Console


class All(Callback):
    def on_multirun_end(self, config: DictConfig, **kwargs: Any) -> None:
        result_file = config["combined_results_file"]
        df = pd.read_csv(result_file)
        # Filter out rows where 'exit_with_error' is True
        filtered_data = df[df["exit_with_error"] == False]

        # Group by solvername and calculate statistics
        stats = (
            filtered_data.groupby(["task", "benchmark_name", "solver_name"])
            .agg(
                total_runs=("run", "count"),
                mean_perfcounter_time=("perfcounter_time", "mean"),
                mean_user_sys_time=("user_sys_time", "mean"),
                num_timed_out=("timed_out", lambda x: x.sum()),
                num_not_timed_out=("timed_out", lambda x: (~x).sum()),
                proportion_timed_out=("timed_out", "mean"),
            )
        )

        print(stats)


class MeanRuntime(Callback):
    def on_multirun_end(self, config: DictConfig, **kwargs: Any) -> None:
        utils.create_callback_chain(config.hydra.callbacks, "mean_runtime")
        os.makedirs(config["statistics_output_dir"], exist_ok=True)

        result_file = config["combined_results_file"]
        # print(config.hydra.callbacks)
        # Check if files exists before reading
        if not os.path.exists(result_file):
            print(f"File {result_file} does not exist")
            return None
        df = pd.read_csv(result_file)

        # Group by solvername and calculate statistics
        stats = (
            df.groupby(["task", "benchmark_name", "solver_name"])
            .agg(
                mean_perfcounter_time=("perfcounter_time", "mean"),
                mean_user_sys_time=("user_sys_time", "mean"),
            )
            .reset_index()
        )

        # utils.print_df_by_groups(stats, ['task', 'benchmark_name'])
        utils.print_grouped_dataframe_as_rich_table(
            stats, title="Mean Runtime Statistics", grouping=["task", "benchmark_name"]
        )

        # Save the statistics to a csv file
        mean_runtime_result_file = os.path.join(
            config["statistics_output_dir"], "mean_runtime.csv"
        )
        stats.to_csv(mean_runtime_result_file)

        # Write filepath to evaluation file index
        utils.write_evaluation_file_to_index(
            mean_runtime_result_file, config["evaluation_result_index_file"]
        )


class Timeouts(Callback):

    def __init__(self, dump_files: bool) -> None:
        self.dump_files = dump_files

    def on_multirun_end(self, config: DictConfig, **kwargs: Any) -> None:
        # Add this callback to the chain
        utils.create_callback_chain(config.hydra.callbacks, "timeouts")

        # Ensure that the statistics output directory exists
        os.makedirs(config["statistics_output_dir"], exist_ok=True)
        result_file = config["combined_results_file"]

        # Check if the combined results file exists
        if not os.path.exists(result_file):
            print(f"File {result_file} does not exist")
            return None

        # Load the combined results into a DataFrame
        df = pd.read_csv(result_file)

        # Group by task, benchmark, and solver; count the number of True entries in 'timed_out'
        stats = (
            df.groupby(["task", "benchmark_name", "solver_name"])
            .agg(timeouts=("timed_out", lambda x: x.sum()))
            .reset_index()
        )

        # Save the timeouts statistics to a CSV file
        timeouts_result_file = os.path.join(
            config["statistics_output_dir"], "timeouts.csv"
        )
        stats.to_csv(timeouts_result_file, index=False)

        # Display the grouped timeouts statistics in a formatted table
        utils.print_grouped_dataframe_as_rich_table(
            stats, title="Timeouts Statistics", grouping=["task", "benchmark_name"]
        )

        # Register the result file in the evaluation file index
        utils.write_evaluation_file_to_index(
            timeouts_result_file, config["evaluation_result_index_file"]
        )

        if self.dump_files:
            # Dump all instances with timed_out = True to a file
            timed_out_instances = df[df["timed_out"] == True]
            timed_out_dump_file = os.path.join(
                config["statistics_output_dir"], "timed_out_instances.csv"
            )
            timed_out_instances.to_csv(timed_out_dump_file, index=False)


class Errors(Callback):

    def __init__(self, dump_files: bool) -> None:
        self.dump_files = dump_files

    def on_multirun_end(self, config: DictConfig, **kwargs: Any) -> None:
        # Add this callback to the chain
        utils.create_callback_chain(config.hydra.callbacks, "errors")

        # Ensure that the statistics output directory exists
        os.makedirs(config["statistics_output_dir"], exist_ok=True)
        result_file = config["combined_results_file"]

        # Check if the combined results file exists
        if not os.path.exists(result_file):
            print(f"File {result_file} does not exist")
            return None

        # Load the combined results into a DataFrame
        df = pd.read_csv(result_file)

        # Group by task, benchmark, and solver; count the number of True entries in 'timed_out'
        stats = (
            df.groupby(["task", "benchmark_name", "solver_name"])
            .agg(errors=("exit_with_error", lambda x: x.sum()))
            .reset_index()
        )

        # Save the timeouts statistics to a CSV file
        errors_result_file = os.path.join(config["statistics_output_dir"], "errors.csv")
        stats.to_csv(errors_result_file, index=False)

        # Display the grouped timeouts statistics in a formatted table
        utils.print_grouped_dataframe_as_rich_table(
            stats, title="Error Statistics", grouping=["task", "benchmark_name"]
        )

        # Register the result file in the evaluation file index
        utils.write_evaluation_file_to_index(
            errors_result_file, config["evaluation_result_index_file"]
        )

        if self.dump_files:
            # Dump all instances with timed_out = True to a file
            error_out_instances = df[df["exit_with_error"] == True]
            error_out_dump_file = os.path.join(
                config["statistics_output_dir"], "errors_instances.csv"
            )
            error_out_instances.to_csv(error_out_dump_file, index=False)


class Coverage(Callback):
    def on_multirun_end(self, config: DictConfig, **kwargs: Any) -> None:
        utils.create_callback_chain(config.hydra.callbacks, "coverage")
        os.makedirs(config["statistics_output_dir"], exist_ok=True)
        result_file = config["combined_results_file"]

        if not os.path.exists(result_file):
            print(f"File {result_file} does not exist")
            return None

        df = pd.read_csv(result_file)

        # Group by solvername and calculate statistics
        stats = (
            df.groupby(["task", "benchmark_name", "solver_name"])
            .agg(coverage=("solver_output_valid", lambda x: (x).mean()))
            .reset_index()
        )

        # Save the statistics to a csv file
        coverage_result_file = os.path.join(
            config["statistics_output_dir"], "coverage.csv"
        )
        stats.to_csv(coverage_result_file)

        # utils.print_df_by_groups(stats, ['task', 'benchmark_name'])
        utils.print_grouped_dataframe_as_rich_table(
            stats, title="Coverage Statistics", grouping=["task", "benchmark_name"]
        )

        # Write filepath to evaluation file index
        utils.write_evaluation_file_to_index(
            coverage_result_file, config["evaluation_result_index_file"]
        )


class Invalid(Callback):

    def __init__(self, dump_files: bool) -> None:
        self.dump_files = dump_files

    def on_multirun_end(self, config: DictConfig, **kwargs: Any) -> None:
        # Add this callback to the chain
        utils.create_callback_chain(config.hydra.callbacks, "invalid")

        # Ensure that the statistics output directory exists
        os.makedirs(config["statistics_output_dir"], exist_ok=True)
        result_file = config["combined_results_file"]

        # Check if the combined results file exists
        if not os.path.exists(result_file):
            print(f"File {result_file} does not exist")
            return None

        # Load the combined results into a DataFrame
        df = pd.read_csv(result_file)

        # Group by task, benchmark, and solver; count the number of True entries in 'timed_out'
        stats = (
            df.groupby(["task", "benchmark_name", "solver_name"])
            .agg(invalid=("solver_output_valid", lambda x: (~x).sum()))
            .reset_index()
        )

        # Save the timeouts statistics to a CSV file
        invalid_result_file = os.path.join(
            config["statistics_output_dir"], "invalid.csv"
        )
        stats.to_csv(invalid_result_file, index=False)

        # Display the grouped timeouts statistics in a formatted table
        utils.print_grouped_dataframe_as_rich_table(
            stats, title="Invalid Statistics", grouping=["task", "benchmark_name"]
        )

        # Register the result file in the evaluation file index
        utils.write_evaluation_file_to_index(
            invalid_result_file, config["evaluation_result_index_file"]
        )

        if self.dump_files:
            # Dump all instances with timed_out = True to a file
            invalid_out_instances = df[df["solver_output_valid"] == False]
            invalid_out_dump_file = os.path.join(
                config["statistics_output_dir"], "invalid_instances.csv"
            )
            invalid_out_instances.to_csv(invalid_out_dump_file, index=False)


class Solved(Callback):

    def __init__(self, dump_files: bool) -> None:
        self.dump_files = dump_files

    def on_multirun_end(self, config: DictConfig, **kwargs: Any) -> None:
        # Add this callback to the chain
        utils.create_callback_chain(config.hydra.callbacks, "solved")

        # Ensure that the statistics output directory exists
        os.makedirs(config["statistics_output_dir"], exist_ok=True)
        result_file = config["combined_results_file"]

        # Check if the combined results file exists
        if not os.path.exists(result_file):
            print(f"File {result_file} does not exist")
            return

        # Load the combined results into a DataFrame
        df = pd.read_csv(result_file)

        # Calculate a boolean mask for solved instances:
        # - timed_out is False
        # - exit_with_error is False
        # - solver_output_valid is True
        solved_mask = (
            (~df["timed_out"]) & (~df["exit_with_error"]) & (df["solver_output_valid"])
        )
        # Create a new column 'solved' (1 if solved, 0 otherwise)
        df["solved"] = solved_mask.astype(int)

        # Group by task, benchmark, and solver; count the number of solved instances
        stats = (
            df.groupby(["task", "benchmark_name", "solver_name"])
            .agg(solved=("solved", "sum"))
            .reset_index()
        )

        # Save the solved statistics to a CSV file
        solved_result_file = os.path.join(config["statistics_output_dir"], "solved.csv")
        stats.to_csv(solved_result_file, index=False)

        # Display the grouped solved statistics in a formatted table
        utils.print_grouped_dataframe_as_rich_table(
            stats, title="Solved Statistics", grouping=["task", "benchmark_name"]
        )

        # Register the result file in the evaluation file index
        utils.write_evaluation_file_to_index(
            solved_result_file, config["evaluation_result_index_file"]
        )


        if self.dump_files:
            # Dump all instances with timed_out = True to a file
            solved_out_instances = df[df["solved"] == 1]
            solved_out_dump_file = os.path.join(
                config["statistics_output_dir"], "solved_instances.csv"
            )
            solved_out_instances.to_csv(solved_out_dump_file, index=False)


# from rich.table import Table
# from rich.panel import Panel
# from rich.text import Text

console = Console()


class AggreateEvaluationResults(Callback):
    """This callback is used to aggregate the evaluation results into a single file"""

    def on_multirun_end(self, config: DictConfig, **kwargs: Any) -> None:
        utils.create_callback_chain(
            config.hydra.callbacks, "aggregate_evaluation_results"
        )
        os.makedirs(config["statistics_output_dir"], exist_ok=True)
        index_file = config["evaluation_result_index_file"]
        output_file = config["evaluation_combined_results_file"]
        # print(f"Aggregating evaluation results from {index_file} into {output_file}")
        try:
            # List to store individual dataframes
            dataframes = []

            # Read the index file line by line
            with open(index_file, "r") as file:
                file_paths = file.readlines()

            # Process each CSV file
            for file_path in file_paths:
                file_path = file_path.strip()  # Remove any leading/trailing whitespace
                if file_path:  # Ensure the line is not empty
                    try:
                        # Read the CSV file
                        df = pd.read_csv(file_path, index_col=0)
                        dataframes.append(df)
                        # print(f"Loaded {file_path}")
                    except Exception as e:
                        print(f"Error reading {file_path}: {e}")

            # Combine all dataframes
            if dataframes:
                # Assuming 'dataframes' is a list of DataFrames and 'key_column' is the column to merge on
                combined_df = reduce(
                    lambda left, right: pd.merge(
                        left,
                        right,
                        on=["task", "benchmark_name", "solver_name"],
                        how="inner",
                    ),
                    dataframes,
                )

                # utils.print_df_by_groups(combined_df, ['task', 'benchmark_name'])
                utils.print_grouped_dataframe_as_rich_table(
                    combined_df,
                    title="Aggregated Statistics",
                    grouping=["task", "benchmark_name"],
                )
                # Save to the output CSV file
                combined_df.to_csv(output_file, index=False)
                console.print(
                    f"[bold green]✔ Results aggregated into {output_file}[/bold green]"
                )
            else:
                print("No dataframes to aggregate.")

        except Exception as e:
            print(f"An error occurred: {e}")


class PenalizedAverageRuntime2(Callback):
    def on_multirun_end(self, config: DictConfig, **kwargs: Any) -> None:
        """
        This callback calculates the Penalized Average Runtime (PAR_α) after
        all runs are complete. It assumes there's an aggregated CSV file
        containing at least:
            - 'perfcounter_time' (float): the runtime of each instance
            - 'solver_output_valid' (bool): indicates if a solver succeeded
            - 'solver_name' (str): name of the solver
            - 'task' (str): optional grouping column
            - 'benchmark_name' (str): optional grouping column

        The callback will:
            1. Read the aggregated CSV.
            2. Compute T′_i = T_i if solver_output_valid, else α * T_max.
            3. Group by (task, benchmark_name, solver_name) and calculate the
               mean of T′_i for PAR_α.
            4. Save to par_runtime.csv and register that file in an index file.
        """

        # 1. Print the callback chain with this callback highlighted
        current_callback_name = "PAR2"
        utils.create_callback_chain(config.hydra.callbacks, current_callback_name)
        os.makedirs(config["statistics_output_dir"], exist_ok=True)

        # 2. Read the aggregated CSV file that combines all results
        result_file = config.get("combined_results_file")
        if not result_file or not os.path.exists(result_file):
            print(f"File '{result_file}' does not exist. Skipping PAR calculation.")
            return

        df = pd.read_csv(result_file)
        par_stats = calculate_par_score(df, config.get("timeout", 600), 2)

        # print(f"Calculated PAR2 score with timeout {config.timeout} statistics:\n")
        # utils.print_df_by_groups(par_stats, ['task', 'benchmark_name'])
        utils.print_grouped_dataframe_as_rich_table(
            par_stats, title="PAR2 Statistics", grouping=["task", "benchmark_name"]
        )

        # 6. Save the PAR results to a CSV file
        output_dir = config.get("statistics_output_dir", ".")
        par_runtime_file = os.path.join(output_dir, "par_2_score.csv")
        par_stats.to_csv(par_runtime_file, index=False)

        # 7. Optionally, register this file in the evaluation file index
        index_file = config.get("evaluation_result_index_file")
        if index_file:
            utils.write_evaluation_file_to_index(par_runtime_file, index_file)


class PenalizedAverageRuntime10(Callback):
    def on_multirun_end(self, config: DictConfig, **kwargs: Any) -> None:
        """
        This callback calculates the Penalized Average Runtime (PAR_α) after
        all runs are complete. It assumes there's an aggregated CSV file
        containing at least:
            - 'perfcounter_time' (float): the runtime of each instance
            - 'solver_output_valid' (bool): indicates if a solver succeeded
            - 'solver_name' (str): name of the solver
            - 'task' (str): optional grouping column
            - 'benchmark_name' (str): optional grouping column

        The callback will:
            1. Read the aggregated CSV.
            2. Compute T′_i = T_i if solver_output_valid, else α * T_max.
            3. Group by (task, benchmark_name, solver_name) and calculate the
               mean of T′_i for PAR_α.
            4. Save to par_runtime.csv and register that file in an index file.
        """

        # 1. Print the callback chain with this callback highlighted
        current_callback_name = "PAR10"
        utils.create_callback_chain(config.hydra.callbacks, current_callback_name)
        os.makedirs(config["statistics_output_dir"], exist_ok=True)

        # 2. Read the aggregated CSV file that combines all results
        result_file = config.get("combined_results_file")
        if not result_file or not os.path.exists(result_file):
            print(f"File '{result_file}' does not exist. Skipping PAR calculation.")
            return

        df = pd.read_csv(result_file)
        par_stats = calculate_par_score(df, config.get("timeout", 600), 10)

        # print(f"Calculated PAR10 score with timeout {config.timeout} statistics:\n")
        # utils.print_df_by_groups(par_stats, ['task', 'benchmark_name'])
        utils.print_grouped_dataframe_as_rich_table(
            par_stats, title="PAR10 Statistics", grouping=["task", "benchmark_name"]
        )

        # 6. Save the PAR results to a CSV file
        output_dir = config.get("statistics_output_dir", ".")
        par_runtime_file = os.path.join(output_dir, "par_10_score.csv")
        par_stats.to_csv(par_runtime_file, index=False)

        # 7. Optionally, register this file in the evaluation file index
        index_file = config.get("evaluation_result_index_file")
        if index_file:
            utils.write_evaluation_file_to_index(par_runtime_file, index_file)


def calculate_par_score(df: pd.DataFrame, t_max: int, alpha: int) -> pd.DataFrame:
    # 3. Retrieve T_max (timeout) and α (penalty factor) from the config
    #    Provide defaults if not specified
    # 4. Compute penalized runtime for each instance
    #    If solver_output_valid is True -> T'_i = T_i
    #    else -> T'_i = α * T_max
    df[f"PAR_{alpha}"] = df.apply(
        lambda row: (
            row["perfcounter_time"] if row["solver_output_valid"] else alpha * t_max
        ),
        axis=1,
    )
    # 5. Group by relevant columns and calculate the average penalized time (PAR_α)
    #    Feel free to adjust grouping columns as needed
    output_column = f"PAR_{alpha}"
    par_stats = (
        df.groupby(["task", "benchmark_name", "solver_name"], dropna=False)
        .agg(**{output_column: (f"PAR_{alpha}", "mean")})
        .reset_index()
    )
    return par_stats
