# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Dict, List, Optional, Sequence, Union

from lisa.executable import Tool
from lisa.operating_system import CBLMariner
from lisa.util import UnsupportedDistroException


class Tpm2(Tool):
    """tpm2 provides a toolset based on tpm2-tss to interact with TPM 2.0 devices"""

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
            raise UnsupportedDistroException(
                self.node.os,
                f"tool {self.command} can't be installed in {self.node.os.name}.",
            )
        return self._check_exists()

    def pcrread(
        self, pcrs: Optional[Union[int, Sequence[int]]] = None
    ) -> Dict[int, str]:
        """List PCR values

        A Platform Configuration Register (PCR) is a memory location in the TPM that
        stores cryptographic measurements of a system's state.

        Example command/output
        $ tpm2 pcrread sha256:4,7
          sha256:
            4 : 0x0000000000000000000000000000000000000000000000000000000000000003
            7 : 0x0000000000000000000000000000000000000000000000000000000000000003
        """
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
