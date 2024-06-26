import json
import logging
import os
import subprocess
import sys
import text
import typer
import constants

from choice import get_mnemonic, select_network, select_vm
from setup import install_docker, install_golang, install_postgresql
from options import MINIMOVE, MINIWASM, VMChoice, bcolors
from progress import setup_progress
from typing_extensions import Annotated

app = typer.Typer()

logging.basicConfig(level=logging.INFO)


def clone_minitia_repository(vm):
    """
    Clones the minitia repository for the specified VM type.

    Args:
        vm (VMChoice): The minitia VM type for which the repository should be cloned.

    Raises:
        ValueError: If an invalid VM choice is provided.
        subprocess.CalledProcessError: If the cloning process fails.
    """
    choice = get_repository_choice(vm)
    repository_url = f"https://github.com/initia-labs/{choice.name}.git"
    logging.info(f"Cloning minitia repository from {repository_url}")

    try:
        subprocess.run(
            ["git", "clone", repository_url],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logging.info("Repository cloned successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to clone repository: {e}")
        raise


def get_repository_choice(vm):
    if vm == VMChoice.MINIMOVE:
        return MINIMOVE
    elif vm == VMChoice.MINIWASM:
        return MINIWASM
    else:
        raise ValueError("Invalid VM choice")


def install_binary(vm):
    choice = MINIMOVE
    if vm == VMChoice.MINIMOVE:
        choice = MINIMOVE
    elif vm == VMChoice.MINIWASM:
        choice = MINIWASM

    print(bcolors.OKGREEN + f"Installing minitia binary" + bcolors.ENDC)
    os.chdir(f"{os.getcwd()}/{choice.name}")
    progress, task = setup_progress(f"Installing {choice.name} binary...", 100)
    try:
        subprocess.run(
            ["make", "install"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        progress.update(task, advance=100)
        print(bcolors.OKGREEN + "Installation completed successfully." + bcolors.ENDC)
    except subprocess.CalledProcessError as e:
        print(bcolors.RED + f"Failed to run 'make install': {e}" + bcolors.ENDC)
        sys.exit(1)


def launch_minitia(network, chain_id, denom, sequencer_mnemonic):
    config_data = setup_config_data(chain_id, denom)
    config_path = write_config_to_file(config_data)

    print(f"Minitia configuration file created at {config_path}")
    launch_command = build_launch_command(
        sequencer_mnemonic, network.chain_id, config_path
    )
    try:
        subprocess.run(" ".join(launch_command), shell=True, check=True)
        print("Minitiad launched successfully with the provided configuration.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to launch minitiad: {e}")
        sys.exit(1)


def setup_config_data(chain_id, denom):
    config_data = {
        "l1_config": {
            "rpc_url": constants.L1_RPC_URI,
            "gas_prices": constants.L1_GAS_PRICES,
        },
        "l2_config": {
            "chain_id": chain_id
            or input(
                "Please enter the Minitia Chain ID to use (leave empty to use autogenerated value): "
            ).strip(),
            "denom": denom or constants.DEFAULT_L2_GAS_DENOM,
        },
    }
    if denom == "umin":
        user_denom = input(
            "Please enter the default gas denom for the minitia (leave empty to use default value): "
        ).strip()
        config_data["l2_config"]["denom"] = (
            user_denom if user_denom else constants.DEFAULT_L2_GAS_DENOM
        )
    return config_data


def write_config_to_file(config_data):
    print(config_data)
    config_path = os.path.join(os.getcwd(), "minitia_config.json")
    with open(config_path, "w") as config_file:
        json.dump(config_data, config_file, indent=4)
    return config_path


def build_launch_command(sequencer_mnemonic, chain_id, config_path):
    return [
        "echo",
        f'"{sequencer_mnemonic}"',
        "|",
        "minitiad",
        "launch",
        chain_id,
        "--with-config",
        config_path,
    ]


def collect_minitia_config():
    """
    Loads the L2 chain ID from the Minitia configuration file.

    Returns:
        str: The L2 chain ID loaded from the configuration file.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        KeyError: If the 'chain_id' key is missing in the L2 configuration.
        json.JSONDecodeError: If the configuration file is not valid JSON.
    """
    config_file_path = os.path.join(
        os.path.expanduser("~"), ".minitia", "artifacts", "config.json"
    )
    try:
        with open(config_file_path, "r") as file:
            config_data = json.load(file)
            l2_chain_id = config_data["l2_config"]["chain_id"]
            logging.info(f"Loaded L2 chain ID: {l2_chain_id}")
            return l2_chain_id
    except FileNotFoundError:
        logging.error("Error: config.json file not found.")
        raise
    except KeyError:
        logging.error("Error: 'chain_id' not found in L2 configuration.")
        raise
    except json.JSONDecodeError:
        logging.error("Error: config.json is not a valid JSON file.")
        raise


def run_opinit_bot(bot: str, version="v0.1.16"):
    """
    Starts a Docker container for a specified bot using a given version.

    Args:
        bot (str): The name of the bot to run.
        version (str): The Docker image version to use.

    Raises:
        subprocess.CalledProcessError: If the Docker container fails to start.
    """
    docker_image = f"ghcr.io/initia-labs/opinit-bots:{version}"
    docker_command = (
        f"docker run -d -p 5432:5432 --network host "
        f"-v $(pwd)/envs/.env.{bot}:/usr/src/app/.env.{bot} "
        f"{docker_image} prod:{bot} --env-file .env.{bot}"
    )
    try:
        with setup_progress(f"Starting {bot} bot...") as progress:
            subprocess.run(docker_command, check=True, shell=True)
            progress.update(completed=100)
        logging.info(f"Docker container for {bot} started successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to start Docker container for {bot}: {e}")
        raise


@app.command()
def setup():
    print(bcolors.OKGREEN + text.WELCOME_MESSAGE + bcolors.ENDC)
    install_golang()
    install_postgresql()
    install_docker()


@app.command()
def start(
    vm: Annotated[
        str, typer.Option(help="Minitia VM to deploy. One of 'minimove' or 'miniwasm'")
    ] = "",
    l1: Annotated[
        str,
        typer.Option(
            help="Initia L1 Chain ID to connect to. One of 'mainnet' or 'testnet'"
        ),
    ] = "",
    mnemonic: Annotated[
        str,
        typer.Option(
            help="Mnemonic to use for the minitia bridge executor. This address needs to be funded with gas on the selected L1 chain."
        ),
    ] = "",
    chain_id: Annotated[
        str,
        typer.Option(
            help="Minitia Chain ID to use. If not provided, a random one will be generated."
        ),
    ] = "",
    denom: Annotated[
        str,
        typer.Option(
            help=f"Default gas denom for the minitia. If not provided, {constants.DEFAULT_L2_GAS_DENOM} will be used"
        ),
    ] = constants.DEFAULT_L2_GAS_DENOM,
):
    vm = select_vm(vm)

    network = select_network(l1)
    mnemonic = get_mnemonic(mnemonic)
    clone_minitia_repository(vm)
    install_binary(vm)
    launch_minitia(network, chain_id, denom, mnemonic)
    l2_chain_id = collect_minitia_config()


@app.command()
def opinit():
    run_opinit_bot("executor")
    run_opinit_bot("batch")
    run_opinit_bot("challenger")
    run_opinit_bot("output")


if __name__ == "__main__":
    app()
