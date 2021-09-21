# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional, Type

from assertpy.assertpy import assert_that

from lisa.executable import Tool


class Echo(Tool):
    @property
    def command(self) -> str:
        return "echo"

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsEcho

    def _check_exists(self) -> bool:
        return True

    def write_to_file(
        self,
        value: str,
        file: str,
        sudo: bool = False,
        append: bool = False,
        timeout: int = 60,
    ) -> None:
        # Run `echo <value> > <file>`
        cmd = f"{value} > {file}"
        if append:
            cmd = f"{value} >> {file}"
        result = self.run(
            cmd,
            force_run=True,
            shell=True,
            sudo=sudo,
            timeout=timeout,
        ).stdout
        assert_that(result).does_not_contain("Permission denied")


class WindowsEcho(Echo):
    @property
    def command(self) -> str:
        return "cmd /c echo"
