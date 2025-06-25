
import pandas as pd
from typing import Any
from hydra.experimental.callback import Callback
from omegaconf import DictConfig
from src import utils


import http.client, urllib


class SendNotificationOnMultiRunEnd(Callback):
    """
    A custom callback that sends a notification when a multi-run experiment ends.

    This callback uses the Pushover API to notify the user when the experiment has completed.

    Attributes:
        None
    """

    def on_multirun_end(self, config: DictConfig, **kwargs: Any) -> None:
        """
        Sends a Pushover notification when the multi-run experiment finishes.

        Args:
            config (DictConfig): The configuration object containing the experiment details.
                - `config.callbacks.notifications.user` (str): The Pushover user key.
                - `config.callbacks.notifications.token` (str): The Pushover API token.
                - `config.name` (str): The name of the experiment.
            **kwargs (Any): Additional keyword arguments (not used in this implementation).

        Returns:
            None

        Example:
            Given a `config` object with the following structure:
            ```
            config:
                name: "MyExperiment"
                callbacks:
                    notifications:
                        user: "user_key"
                        token: "api_token"
            ```
            This method sends a Pushover notification to the user stating:
            "Your experiment MyExperiment has finished running!"
        """
        print(utils.create_callback_chain(config.hydra.callbacks, 'notify_on_multirun_end'))
        user = config.callbacks.notifications.user
        token = config.callbacks.notifications.token

        experiment_name = config.name
        conn = http.client.HTTPSConnection("api.pushover.net:443")
        conn.request("POST", "/1/messages.json",
            urllib.parse.urlencode({
                "token": token,
                "user": user,
                "message": f"Your experiment {experiment_name} has finished running!",
            }), { "Content-type": "application/x-www-form-urlencoded" })
        response = conn.getresponse()
        print(f"Notification Status: {response.status} - {response.reason}")
        print(f"Notification Details: Experiment '{experiment_name}', User '{user}', Token '{token}'")
        print(f"Notification sent for experiment: {experiment_name}")


class SendNotificationOnJobEnd(Callback):
    """
    A custom callback that sends a notification when a job ends.

    This callback uses the Pushover API to notify the user when the job has completed,
    including details about the solver, task, and benchmark used in the job.

    Attributes:
        None
    """

    def on_job_end(self, config: DictConfig, **kwargs: Any) -> None:
        """
        Sends a Pushover notification when the job ends, including the current solver,
        task, and benchmark.

        Args:
            config (DictConfig): The configuration object containing the job details.
                - `config.callbacks.notifications.user` (str): The Pushover user key.
                - `config.callbacks.notifications.token` (str): The Pushover API token.
                - `config.job.name` (str): The name of the job.
                - `config.solver.name` (str): The name of the current solver.
                - `config.task` (str): The current task.
                - `config.benchmark.name` (str): The name of the benchmark.
            **kwargs (Any): Additional keyword arguments (not used in this implementation).

        Returns:
            None

        Example:
            Given a `config` object with the following structure:
            ```
            config:
                job:
                    name: "probo2-run"
                solver:
                    name: "fudge"
                task: "DC-ID"
                benchmark:
                    name: "ICCMA23_legacy"
                callbacks:
                    notifications:
                        user: "user_key"
                        token: "api_token"
            ```
            This method sends a Pushover notification to the user stating:
            "Your job probo2-run has finished running! Solver: fudge, Task: DC-ID, Benchmark: ICCMA23_legacy"
        """
        print(utils.create_callback_chain(config.hydra.callbacks, 'notify_on_job_end'))
        user = config.callbacks.notifications.user
        token = config.callbacks.notifications.token

        solver_name = config.solver.name
        task = config.task
        benchmark_name = config.benchmark.name

        message = (f"A solver finished in your experiment {config.name} ! Solver: {solver_name}, Task: {task}, Benchmark: {benchmark_name}")

        conn = http.client.HTTPSConnection("api.pushover.net:443")
        conn.request("POST", "/1/messages.json",
                     urllib.parse.urlencode({
                         "token": token,
                         "user": user,
                         "message": message,
                     }),
                     {"Content-type": "application/x-www-form-urlencoded"})
        response = conn.getresponse()
        print(f"Notification Status: {response.status} - {response.reason}")
        print(f"Notification Details: Solver '{solver_name}', Task '{task}', Benchmark '{benchmark_name}', User '{user}', Token '{token}'")

