# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Dict, List, Optional, Sequence, Union

from lisa.executable import Tool
from lisa.operating_system import CBLMariner
from lisa.util import LisaException


class Tpm2(Tool):
    @property
    def command(self) -> str:
        return "tpm2"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        if isinstance(self.node.os, CBLMariner):
            self.node.os.install_packages("tpm2-tools")
        else:
            raise LisaException(
                f"tool {self.command} can't be installed in distro {self.node.os.name}."
            )
        return self._check_exists()

    def pcrread(
        self, pcrs: Optional[Union[int, Sequence[int]]] = None
    ) -> Dict[int, str]:
        alg = "sha256"
        pcrs = self._get_pcr_list(pcrs)
        if len(pcrs) == 0:
            pcrs_arg = "all"
        else:
            pcrs_arg = ",".join(map(str, pcrs))
        cmd = f"pcrread {alg}:{pcrs_arg}"
        cmd_result = self.run(
            cmd,
            expected_exit_code=0,
            expected_exit_code_failure_message="failed to read PCR values",
            shell=True,
            sudo=True,
            force_run=True,
        )
        output = cmd_result.stdout

        lines = [line.strip() for line in output.splitlines()]
        # first line of output will have the format "<alg-name>:", e.g "sha256:"
        assert (
            lines[0][:-1] == alg
        ), "pcrread output does not contain the requested algorithm"

        result = dict()
        for line in lines[1:]:
            pcr, hash_value = line.split(":", 1)
            pcr_index = int(pcr.strip())
            hash_value = hash_value.strip().lower()
            result[pcr_index] = hash_value
        return result

    def _get_pcr_list(self, pcrs: Optional[Union[int, Sequence[int]]]) -> List[int]:
        if pcrs is None:
            return []
        if isinstance(pcrs, int):
            return [pcrs]
        return [pcr for pcr in pcrs]
