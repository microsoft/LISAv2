# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


import sys
import traceback
from datetime import datetime
from logging import DEBUG, INFO, FileHandler
from pathlib import Path, PurePath
from typing import Optional, Tuple

from retry import retry

import lisa.mixin_modules  # noqa: F401
from lisa.parameter_parser.argparser import parse_args
from lisa.util import constants, get_datetime_path
from lisa.util.logger import (
    create_file_handler,
    get_logger,
    remove_handler,
    set_level,
    uninit_logger,
)
from lisa.util.perf_timer import create_timer
from lisa.variable import add_secrets_from_pairs


@retry(FileExistsError, tries=10, delay=0.2)  # type: ignore
def generate_run_path(root_path: Path, run_id: str = "") -> Tuple[PurePath, Path]:
    if run_id:
        # use predefined run_id
        logic_path = PurePath(run_id)
    else:
        # Get current time and generate a Run ID.
        current_time = datetime.utcnow()
        date_of_today = current_time.strftime("%Y%m%d")
        time_of_today = get_datetime_path(current_time)
        logic_path = PurePath(f"{date_of_today}/{time_of_today}")
    local_path = root_path.joinpath(logic_path)
    if local_path.exists():
        raise FileExistsError(
            f"The run path '{local_path}' already exists, "
            f"and not found an unique path."
        )
    local_path.mkdir(parents=True)
    return logic_path, local_path


def initialize_runtime_folder(
    log_path: Optional[Path] = None, run_id: str = ""
) -> None:
    runtime_root = Path("runtime").absolute()

    cache_path = runtime_root.joinpath("cache")
    cache_path.mkdir(parents=True, exist_ok=True)
    constants.CACHE_PATH = cache_path

    # Layout the run time folder structure.
    if log_path:
        # if log path is relative path, join with root.
        if not log_path.is_absolute():
            log_path = runtime_root / log_path
    else:
        log_path = runtime_root / "runs"
    logic_path, local_path = generate_run_path(log_path, run_id=run_id)

    constants.RUN_ID = logic_path.name
    constants.RUN_LOGIC_PATH = logic_path
    constants.RUN_LOCAL_LOG_PATH = local_path


def main() -> int:
    total_timer = create_timer()
    log = get_logger()
    exit_code: int = 0
    file_handler: Optional[FileHandler] = None

    try:
        args = parse_args()

        initialize_runtime_folder(args.log_path, args.run_id)

        log_level = DEBUG if (args.debug) else INFO
        set_level(log_level)

        file_handler = create_file_handler(
            Path(f"{constants.RUN_LOCAL_LOG_PATH}/lisa-{constants.RUN_ID}.log")
        )

        log.info(f"Python version: {sys.version}")
        log.info(f"local time: {datetime.now().astimezone()}")

        # We don't want command line args logging to leak any provided
        # secrets, if any ("s:key:value" syntax)
        add_secrets_from_pairs(args.variables)

        log.debug(f"command line args: {sys.argv}")
        log.info(f"run local path: {constants.RUN_LOCAL_LOG_PATH}")

        exit_code = args.func(args)
        assert isinstance(exit_code, int), f"actual: {type(exit_code)}"
    finally:
        log.info(f"completed in {total_timer}")
        if file_handler:
            remove_handler(log_handler=file_handler, logger=log)
        uninit_logger()

    return exit_code


if __name__ == "__main__":
    exit_code = 0
    try:
        exit_code = main()
    except Exception as exception:
        exit_code = -1
        log = get_logger()
        try:
            log.exception(exception)
        except Exception:
            # if there is any exception in log class, they have to be caught and show
            # on console only
            traceback.print_exc()
    finally:
        sys.exit(exit_code)
