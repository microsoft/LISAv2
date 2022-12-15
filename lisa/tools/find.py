# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import List

from lisa.executable import Tool
from lisa.util import LisaException


class Find(Tool):
    @property
    def command(self) -> str:
        return "find"

    @property
    def can_install(self) -> bool:
        return False

    def find_files(
        self,
        start_path: PurePath,
        name_pattern: str = "",
        path_pattern: str = "",
        type: str = "",
        ignore_case: bool = False,
        sudo: bool = False,
        ignore_not_exist: bool = False,
    ) -> List[str]:
        if not ignore_not_exist and not self.node.shell.exists(start_path):
            raise LisaException(f"Path {start_path} does not exist.")

        cmd = str(start_path)
        if name_pattern:
            if ignore_case:
                cmd += f" -iname '{name_pattern}'"
            else:
                cmd += f" -name '{name_pattern}'"
        if path_pattern:
            if ignore_case:
                cmd += f" -ipath '{path_pattern}'"
            else:
                cmd += f" -path '{path_pattern}'"
        if type:
            cmd += f" -type '{type}'"

        # for possibility of newline character in the file/folder name.
        cmd += " -print0"

        result = self.run(cmd, sudo=sudo, expected_exit_code=0)
        return list(filter(None, result.stdout.split("\x00")))
