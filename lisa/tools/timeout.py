from lisa.executable import ExecutableResult, Tool
from lisa.util.constants import SIGTERM


class Timeout(Tool):
    @property
    def command(self) -> str:
        return "timeout"

    @property
    def can_install(self) -> bool:
        return False

    def run_with_timeout(
        self, command: str, timeout: int, signal: int = SIGTERM, kill_timeout: int = 0
    ) -> ExecutableResult:
        # timeout [OPTION] DURATION COMMAND [ARG]...
        params = f"-s {signal} --preserve-status {timeout} {command}"
        if kill_timeout:
            params = f"--kill-after {kill_timeout} " + params
        command_timeout = timeout
        if kill_timeout:
            command_timeout = kill_timeout + 10

        return self.run(
            parameters=params,
            force_run=True,
            shell=True,
            sudo=True,
            timeout=command_timeout,
        )
