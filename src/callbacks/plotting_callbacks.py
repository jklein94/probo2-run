import os
import pandas as pd
import matplotlib.pyplot as plt
from typing import Any
from hydra.experimental.callback import Callback
from omegaconf import DictConfig
import seaborn as sns

from src import utils  # your utility module (e.g., create_callback_chain, write_evaluation_file_to_index)

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

class CactusPlot(Callback):
    def __init__(self, combine_multiple_runs: bool = False, runtime_key: str = "perfcounter_time"):
        """
        Constructor to initialize CactusPlot with options from cactus_plot.yaml.

        Args:
            combine_runs (bool): Whether to combine runs or not.
            runtime_key (str): The key to use for runtime ('perfcounter_time' or 'user_sys_time').
        """
        self.combine_runs = combine_multiple_runs
        self.runtime_key = runtime_key


    def on_multirun_end(self, config: DictConfig, **kwargs: Any) -> None:
        """
        Creates multiple cactus plots from the aggregated solver data once all
        multirun executions have finished — one plot per (task, benchmark_name)
        combination.
        """

        # 1. Print the callback chain with the current callback highlighted
        current_callback_name = "cactus_plot"
        utils.create_callback_chain(config.hydra.callbacks, current_callback_name)
        #console.print(Panel.fit("[bold magenta]Executing Callback: Cactus Plot Generation[/bold magenta]", border_style="bright_magenta"))

        # 2. Get the aggregated results file path from config
        result_file = config.get("combined_results_file")
        if not result_file or not os.path.exists(result_file):
            console.print(f"[bold bright_red]Error:[/bold bright_red] File '[bright_white]{result_file}[/bright_white]' does not exist. Skipping cactus plot.")
            return

        console.print(f"[bold bright_cyan]Loading data from:[/bold bright_cyan] [bright_white]{result_file}[/bright_white]")

        # 3. Load the data
        df = pd.read_csv(result_file)

        # 4. Column name config (optional)
        runtime_col = self.runtime_key
        valid_col = "solver_output_valid"
        task_col = "task"
        bench_col = "benchmark_name"

        # Aggregate results of multiple runs if needed
        df = df.groupby(["task", "benchmark_name", "solver_name", "instance"]).agg(
            {runtime_col: "mean", valid_col: "all"}  # Keep only instances solved in all runs
        ).reset_index()

        # 5. Filter data for solved instances
        df_solved = df[df[valid_col] == True].copy()
        if df_solved.empty:
            console.print("[bold bright_red]No solved instances found. Cactus plots will not be generated.[/bold bright_red]")
            return

        # 6. Group the dataframe by (task, benchmark_name)
        task_bench_groups = df_solved.groupby([task_col, bench_col])

        output_dir = config.get("plots_output_dir", ".")
        os.makedirs(output_dir, exist_ok=True)

        console.print(f"[bold bright_cyan]Saving plots to:[/bold bright_cyan] [bright_white]{output_dir}[/bright_white]")

        # 7. Iterate through each (task, benchmark_name) combination
        for (task_val, bench_val), group_df in task_bench_groups:
            console.print(f"[bold bright_blue]Generating cactus plot for:[/bold bright_blue] Task: [bright_white]{task_val}[/bright_white], Benchmark: [bright_white]{bench_val}[/bright_white]")

            # Create a figure
            fig, ax = plt.subplots(figsize=(10, 6))
            frames = []

            # 7a. Group by solver_name to generate lines in the cactus plot
            for solver_name, solver_df in group_df.groupby("solver_name"):
                sorted_times = solver_df[runtime_col].sort_values().reset_index(drop=True)
                x = range(1, len(sorted_times) + 1)
                y = sorted_times

                t = pd.DataFrame({'time': y, 'n_solved': x})
                t['solver_name'] = solver_name
                frames.append(t)

            data = pd.concat(frames, ignore_index=True)

            sns.lineplot(ax=ax, data=data, y='time', x='n_solved',
                        hue='solver_name', style='solver_name',
                        markers=True, dashes=False)

            ax.set(title=f"Cactus Plot\nTask: {task_val}, Benchmark: {bench_val}",
                ylabel="CPU Time (seconds)", xlabel="# of Instances Solved")
            fig.tight_layout()

            # 7b. Create a safe file name
            safe_task = str(task_val).replace(" ", "_")
            safe_bench = str(bench_val).replace(" ", "_")
            plot_filename = f"cactus_plot_{safe_task}_{safe_bench}.png"
            plot_path = os.path.join(output_dir, plot_filename)

            plt.savefig(plot_path, bbox_inches="tight")
            plt.close()

            console.print(f"[bold bright_green]✔ Saved cactus plot:[/bold bright_green] [bright_white]{plot_path}[/bright_white]")

        # console.print(Panel.fit("[bold bright_green]Cactus Plot Generation Completed Successfully[/bold bright_green]", border_style="bright_green"))
