# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.tools.lsblk import Lsblk
from lisa.tools.swapon import SwapOn


class Swap(Tool):
    @property
    def command(self) -> str:
        raise NotImplementedError()

    def _check_exists(self) -> bool:
        return True

    def is_swap_enabled(self) -> bool:
        # swapon lists the swap files and partitions
        # example output:
        # /swapfile file 1024M 507.4M   -1
        swapon = self.node.tools[SwapOn].run("-s").stdout
        if "swap" in swapon:
            return True

        # lsblk lists swap partitions
        # example output:
        # sdb2   8:18   0   7.6G  0 part [SWAP]
        lsblk = self.node.tools[Lsblk].run().stdout
        if "SWAP" in lsblk:
            return True

        return False
