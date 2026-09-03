# probo2-run

## Installation

- Clone the repository

```
git clone https://github.com/jklein94/probo2-hydra.git
```

- Navigate to project folder and create a virtual enviroment

```bash
python3 -m venv probo2_env
```

or if use Anaconda:

```bash
conda create -n probo2_env pip
```

- Activate the created enviroment

 ```bash
source probo2_env/bin/activate
```

- Install all dependencies

```bash
pip install -r requirements.txt
```


## Quick Start

In this section, we briefly describe the general workflow of `probo2-run` and how experiments are managed.
As you will see, with `probo2-run`, it is easy to set up an experiment. We only need three things:
>
> 1. The argumentation solvers
> 2. The benchmark instances
> 3. A experiment configuration file

After installing the solvers and benchmarks, we can start preparing our first experiment.

To do this, we need to complete the following steps:
>
> 1. Create configuration files for all solvers you want to use.
> 2. Create configuration files for all benchmarks you want to use.
> 3. Create a configuration file for the experiment.

The configuration files must be saved in the corresponding subfolders within the `configs` directory. In each folder, you will also find example configuration files that can be used as templates.

Let's start by creating a YAML file for a solver.
Below is an example of a solver (MySolver.yaml) configuration file in YAML format and a description of the fields:

```yaml
name: MySolver # Name of the solver must be unique!
version: ICCM23
path: /full/path/to/MySolver # Path to the solver executable or script (bash or python)
format: tgf # Supported formats: tgf, apx, i23
interface: legacy # Supported interfaces: legacy (ICCMA15-21 interface), i23  (ICCMA23 interface)
argument: [paramA, paramB] # Optional: List of arguments for the solver
```

- **`name`** *(string, required)*: A unique identifier for the solver.
- **`version`** *(string, optional)*: Specifies the solver version (e.g., ICCM23).
- **`path`** *(string, required)*: The absolute path to the solver executable or script.
- **`format`** *(string, required)*: Defines the supported input format(s). Supported values:
  - `tgf` (Trivial Graph Format)
  - `apx` (Argumentation Framework Format)
  - `i23` (ICCMA23 Format)
- **`interface`** *(string, required)*: Determines the interface the solver adheres to. Options:
  - `legacy` (ICCMA15-21 interface)
  - `i23` (ICCMA23 interface)
- **`argument`** *(list, optional)*: An optional list of arguments that can be passed to the solver during execution.

After creating our solver files, it's time to set up the benchmarks. Below is an example file along with an explanation of the individual fields:


```yaml
name: MyBenchmark # A unique name for the benchmark
path: /path/to/MyBenchmark # Full path to the benchmark directory
query_arg_format: af.arg # Format of the query argument file
format: [tgf, apx, i23] # Supported formats of the benchmark instances
solution_path: /path/to/solutions # Full path to the benchmark solutions
```

- **`name`** *(string, required)*: A unique identifier for the benchmark.
- **`path`** *(string, required)*: The absolute path to the benchmark directory containing the instance files.
- **`query_arg_format`** *(string, required)*: Defines the format of the query argument file used in the benchmark (e.g., `af.arg`).
- **`format`** *(list, required)*: Specifies the supported formats for the benchmark instances. Supported values:
  - `tgf` (Trivial Graph Format)
  - `apx` (Argumentation Framework Format)
  - `i23` (ICCMA23 Format)
- **`solution_path`** *(string, required)*: The absolute path to the directory where the corresponding solutions for the benchmark instances are stored.

Now, we only need a experiment file:

```yaml
# @package _global_

name: MyFirstExperiment # Name of the experiment configuration

hydra:
  sweeper:
    params:
      benchmark: MyBenchmark # The benchmark to be used in the experiment
      solver: MySolver_1, MySolver_2 # List of solvers to be tested
      task: DS-PR, DS-ST # List of tasks to be performed during the experiment
```

The `name` field is used to specify the name of the experiment configuration. In the provided example, the experiment is named `MyFirstExperiment`, which serves as an identifier.

The core of the configuration is nested under the `hydra` section. Hydra is a framework that facilitates flexible configuration management, which is particularly useful when dealing with complex parameter sweeps and multiple experimental conditions. Within `hydra`, the `sweeper` component is defined and is responsible for managing the parameter sweeps during the benchmarking process.

Inside the `sweeper`, the `params` section outlines the specific parameters to be tested. The `benchmark` parameter specifies the benchmark dataset. It is also possible to include multiple benchmarks separated by commas.

> ⚠️ **Note:** You have to specify the actual name of the YAML file, not the name you used inside the file. For example, if my file is called `MyBenchmarkConfig.yaml` you refer to the benchmark with `MyBenchmarkConfig`. Basically you just strip the .yaml. This is also true for the `solver` oprion

The `solver` parameter lists the solvers that will be tested. Multiple solvers can be included, separated by commas, as shown with `MySolver_1, MySolver_2`.

Next, the `task` parameter defines the tasks to be solved during the experiment. In the provided configuration, the tasks are `DS-PR` and `DS-ST`.

During the experiment's execution, each specified solver will be run on the benchmarks, attempting to solve the given tasks. All combinations of solvers, benchmarks, and tasks will be processed.

#### Restricting tasks per solver (optional)

By default every solver in the sweep runs against every swept task. To restrict a specific solver to a subset of tasks, add `solver_task_mapping` to your experiment file, keyed by the solver's `name` field (not the config-group path used under `hydra.sweeper.params.solver`):

```yaml
solver_task_mapping:
  MySolver_1: [DS-PR]
```

Solvers not listed as a key are unaffected and continue to run on all swept tasks. Excluded combinations are skipped at runtime with a console message — no result row or `.out` file is produced for them.



