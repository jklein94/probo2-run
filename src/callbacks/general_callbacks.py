import pandas as pd
from typing import Any
from hydra.experimental.callback import Callback
from omegaconf import DictConfig
from src import utils
from rich.console import Console
from rich.panel import Panel
console = Console()
class AggregateResults(Callback):
    def on_multirun_end(self, config: DictConfig, **kwargs: Any) -> None:
        """
        Callback function that is executed at the end of a multi-run process.
        This function performs the following tasks:
        1. Creates a callback chain using the provided Hydra configuration.
        2. Reads a list of file paths from an index file specified in the configuration.
        3. Loads each CSV file listed in the index file into a pandas DataFrame.
        4. Aggregates all the loaded DataFrames into a single DataFrame.
        5. Saves the aggregated DataFrame to an output CSV file specified in the configuration.
        Args:
            config (DictConfig): The Hydra configuration object containing the necessary file paths.
            **kwargs (Any): Additional keyword arguments (not used in this function).
        Raises:
            Exception: If an error occurs during file reading or DataFrame processing, an error message is printed to the console.
        """

        utils.create_callback_chain(config.hydra.callbacks, 'aggregate_solver_results')

        index_file = config['result_index_file']
        output_file = config['combined_results_file']

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
                        df = pd.read_csv(file_path)
                        dataframes.append(df)
                        console.print(f"[green]Loaded:[/green] {file_path}")
                    except Exception as e:
                        console.print(f"[bold red]Error reading {file_path}: {e}[/bold red]")

            # Combine all dataframes
            if dataframes:
                combined_df = pd.concat(dataframes, ignore_index=True)
                # Save to the output CSV file
                combined_df.to_csv(output_file, index=False)
                console.print(f"")
                console.print(f"[bold green]✔ Results aggregated into {output_file}[/bold green]")
            else:
                console.print("[bold yellow]No dataframes to aggregate.[/bold yellow]")

        except Exception as e:
            console.print(f"[bold red]An error occurred: {e}[/bold red]")