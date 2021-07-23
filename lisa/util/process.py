# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
import pathlib
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Union

import spur  # type: ignore
from assertpy.assertpy import AssertionBuilder, assert_that
from spur.errors import NoSuchCommandError  # type: ignore

from lisa.util.logger import Logger, LogWriter, get_logger
from lisa.util.perf_timer import create_timer
from lisa.util.shell import Shell


@dataclass
class ExecutableResult:
    stdout: str
    stderr: str
    exit_code: Optional[int]
    cmd: Union[str, List[str]]
    elapsed: float

    def __str__(self) -> str:
        return self.stdout

    def assert_exit_code(
        self, expected_exit_code: int = 0, message: str = ""
    ) -> AssertionBuilder:
        message = "\n".join([message, f"get unexpected exit code on cmd {self.cmd}"])
        return assert_that(self.exit_code, message).is_equal_to(expected_exit_code)

    def assert_stderr(
        self, expected_stderr: str = "", message: str = ""
    ) -> AssertionBuilder:
        message = "\n".join([message, f"get unexpected stderr on cmd {self.cmd}"])
        return assert_that(self.stderr, message).is_equal_to(expected_stderr)


# TODO: So much cleanup here. It was using duck typing.
class Process:
    def __init__(
        self,
        id_: str,
        shell: Shell,
        parent_logger: Optional[Logger] = None,
    ) -> None:
        # the shell can be LocalShell or SshShell
        self._shell = shell
        self._id_ = id_
        self._is_posix = shell.is_posix
        self._running: bool = False
        self._log = get_logger("cmd", id_, parent=parent_logger)
        self._process: Optional[spur.local.LocalProcess] = None
        self._result: Optional[ExecutableResult] = None

    def start(
        self,
        command: str,
        shell: bool = False,
        sudo: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
        new_envs: Optional[Dict[str, str]] = None,
        no_error_log: bool = False,
        no_info_log: bool = False,
    ) -> None:
        """
        command include all parameters also.
        """
        stdout_level = logging.INFO
        stderr_level = logging.ERROR
        if no_info_log:
            stdout_level = logging.DEBUG
        if no_error_log:
            stderr_level = stdout_level

        self.stdout_logger = get_logger("stdout", parent=self._log)
        self.stderr_logger = get_logger("stderr", parent=self._log)
        self._stdout_writer = LogWriter(logger=self.stdout_logger, level=stdout_level)
        self._stderr_writer = LogWriter(logger=self.stderr_logger, level=stderr_level)

        # command may be Path object, convert it to str
        command = str(command)
        if shell:
            if not self._is_posix:
                split_command = ["cmd", "/c", command]
            elif sudo:
                split_command = ["sudo", "sh", "-c", command]
            else:
                split_command = ["sh", "-c", command]
        else:
            if sudo and self._is_posix:
                command = f"sudo {command}"
            split_command = shlex.split(command, posix=self._is_posix)

        cwd_path: Optional[str] = None
        if cwd:
            if self._is_posix:
                cwd_path = str(pathlib.PurePosixPath(cwd))
            else:
                cwd_path = str(pathlib.PureWindowsPath(cwd))

        self._log.debug(
            f"cmd: {split_command}, "
            f"cwd: {cwd_path}, "
            f"shell: {shell}, "
            f"sudo: {sudo}, "
            f"posix: {self._is_posix}, "
            f"remote: {self._shell.is_remote}"
        )

        if new_envs is None:
            new_envs = {}

        try:
            self._timer = create_timer()
            self._process = self._shell.spawn(
                command=split_command,
                stdout=self._stdout_writer,
                stderr=self._stderr_writer,
                cwd=cwd_path,
                update_env=new_envs,
                allow_error=True,
                store_pid=self._is_posix,
                encoding="utf-8",
            )
            # save for logging.
            self._cmd = split_command
            self._running = True
        except (FileNotFoundError, NoSuchCommandError) as identifier:
            # FileNotFoundError: not found command on Windows
            # NoSuchCommandError: not found command on remote Posix
            self._result = ExecutableResult(
                "", identifier.strerror, 1, split_command, self._timer.elapsed()
            )
            self._log.log(stderr_level, f"not found command: {identifier}")

    def wait_result(self, timeout: float = 600) -> ExecutableResult:
        timer = create_timer()

        while self.is_running() and timeout >= timer.elapsed(False):
            time.sleep(0.01)

        if timeout < timer.elapsed():
            if self._process is not None:
                self._log.info(f"timeout in {timeout} sec, and killed")
            self.kill()

        if self._result is None:
            assert self._process
            process_result = self._process.wait_for_result()
            self._stdout_writer.close()
            self._stderr_writer.close()
            # cache for future queries, in case it's queried twice.
            self._result = ExecutableResult(
                process_result.output.strip(),
                process_result.stderr_output.strip(),
                process_result.return_code,
                self._cmd,
                self._timer.elapsed(),
            )
            # TODO: The spur library is not very good and leaves open
            # resources (probably due to it starting the process with
            # `bufsize=0`). We need to replace it, but for now, we
            # manually close the leaks.
            if isinstance(self._process, spur.local.LocalProcess):
                popen: subprocess.Popen[str] = self._process._subprocess
                if popen.stdin:
                    popen.stdin.close()
                if popen.stdout:
                    popen.stdout.close()
                if popen.stderr:
                    popen.stderr.close()
            elif isinstance(self._process, spur.ssh.SshProcess):
                if self._process._stdin:
                    self._process._stdin.close()
                if self._process._stdout:
                    self._process._stdout.close()
                if self._process._stderr:
                    self._process._stderr.close()
            self._process = None
            self._log.debug(
                f"execution time: {self._timer}, exit code: {self._result.exit_code}"
            )

        return self._result

    def kill(self) -> None:
        if self._process:
            if self._shell.is_remote:
                # Support remote Posix so far
                self._process.send_signal(9)
            else:
                # local process should use the compiled value
                # the value is different between windows and posix
                self._process.send_signal(signal.SIGTERM)

    def is_running(self) -> bool:
        if self._running and self._process:
            self._running = self._process.is_running()
        return self._running
