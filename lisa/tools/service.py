# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from time import sleep
from typing import Any, Optional, Type

from lisa import schema
from lisa.executable import Tool
from lisa.tools.powershell import PowerShell
from lisa.util import LisaException


class Service(Tool):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        # timeout to wait
        self._command = "/usr/sbin/service"

    @property
    def command(self) -> str:
        return self._command

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsService

    def _check_exists(self) -> bool:
        return False

    def restart(self, name: str) -> None:
        self.run(f"{self.command} {name} restart", shell=True, sudo=True)

    def wait_for_till_ready(self, name: str) -> None:
        raise NotImplementedError()

    def get_status(self, name: str = "") -> schema.ServiceStatus:
        raise NotImplementedError()


class WindowsService(Service):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "powershell"
        self._powershell = self.node.tools[PowerShell]

    @property
    def command(self) -> str:
        return self._command

    def _check_exists(self) -> bool:
        return True

    def restart(self, name: str) -> None:
        self._powershell.run_cmdlet(
            f"Restart-service {name}",
            force_run=True,
        )
        self.wait_for_till_ready(name)

    def wait_for_till_ready(self, name: str) -> None:
        for _ in range(10):
            output = self._powershell.run_cmdlet(
                f"Get-Service {name}",
                force_run=True,
                output_json=True,
            )
            service_status = json.loads(output)
            if schema.ServiceStatus.RUNNING == schema.ServiceStatus(
                service_status["Status"]
            ):
                return

            self._log.debug(
                f"service '{name}' is not ready yet, retrying... after 5 seconds"
            )
            sleep(5)

        raise LisaException(f"service '{name}' failed to start")

    def get_status(self, name: str = "") -> schema.ServiceStatus:
        output = self._powershell.run_cmdlet(
            f"Get-Service {name}",
            force_run=True,
            output_json=True,
        )
        service_status = json.loads(output)
        return schema.ServiceStatus(service_status["Status"])
