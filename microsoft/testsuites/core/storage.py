# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import PurePosixPath
from typing import Optional

from assertpy.assertpy import assert_that

from lisa import (
    LisaException,
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.environment import EnvironmentStatus
from lisa.operating_system import CoreOs
from lisa.tools import Cat, Mount
from lisa.tools.lsblk import Lsblk
from lisa.tools.swapon import SwapOn


@TestSuiteMetadata(
    area="storage",
    category="functional",
    description="""
    This test suite is used to run storage related tests.
    """,
)
class Storage(TestSuite):
    DEFAULT_DISK_TIMEOUT = 300

    # ResourceDisk.MountPoint=/mnt
    _resource_disk_mount_point_regex = re.compile(
        r"^.*ResourceDisk\.MountPoint=(?P<resource_disk_mount_point>\S+)\s.*$"
    )

    # ResourceDisk.EnableSwap=n
    # ResourceDisk.EnableSwap=y
    _resource_disk_enable_swap_regex = re.compile(
        r"^.*ResourceDisk\.EnableSwap=(?P<resource_disk_enable_swap>\S+)\s.*$"
    )

    # /dev/sda1 on / type ext4 (rw,relatime,discard)
    _root_partition_regex = re.compile(
        r"\s*\/dev\/(?P<partition>\D+).*\s+on\s+\/\s+type.*"
    )

    @TestCaseMetadata(
        description="""
        This test will check that VM root disk(os disk) is provisioned
        with the correct timeout.
        Steps:
        1. Find the root disk (os disk) partition for the VM. The root partition
        corresponds to entry with mount point `/' in the `mount` command.
        2. Verify the timeout value for root disk in
        `/sys/block/<partition>/device/timeout` file is set to 300.
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
        ),
    )
    def verify_root_device_timeout(
        self,
        log: Logger,
        node: RemoteNode,
    ) -> None:
        os_disk_partition = self._get_os_disk_partition(log, node)
        output = int(
            node.tools[Cat].run(f"/sys/block/{os_disk_partition}/device/timeout").stdout
        )
        assert_that(output).is_equal_to(self.DEFAULT_DISK_TIMEOUT)

    @TestCaseMetadata(
        description="""
        This test will check that the resource disk is present in the list of mounted
        devices. VMs contain a resource disk, which is not a managed disk. The
        resource disk provides short-term storage for applications and processes, and
        is intended to only store data such as page or swap files.
        Steps:
        1. Get the mount point for the resource disk. If `/var/log/cloud-init.log`
        file is present, mount location is `\\mnt`, otherwise it is obtained from
        `ResourceDisk.MountPoint` entry in `waagent.conf` configuration file.
        2. Get the resource disk partition. In a VM with no data disk, one of `sda`
        or `sdb` is a resource disk partition. The root partition corresponds to
        entry with mount point `/' in the `mount` command, and the other is
        resource disk.
        3. Verify that "/dev/<resource_disk_partition> <mount_point>` entry is
        present in `/etc/mtab` file.
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
        ),
    )
    def verify_resource_disk_mtab_entry(self, log: Logger, node: RemoteNode) -> None:
        resource_disk_mount_point = self._get_data_disk_mount_point(log, node)
        os_disk_partition = self._get_os_disk_partition(log, node)
        if os_disk_partition == "sda":
            mntresource = "/dev/sdb1 " + resource_disk_mount_point
        else:
            mntresource = "/dev/sda1 " + resource_disk_mount_point

        output = node.tools[Cat].run("/etc/mtab").stdout
        if mntresource in output:
            log.debug("ResourceDisk entry is present.")
        else:
            raise LisaException("ResourceDisk entry is not present.")

    @TestCaseMetadata(
        description="""
        This test will check that the swap is correctly configured on the VM.
        Steps:
        1. Check if swap file/partition is configured by checking the output of
        `swapon -s` and `lsblk`.
        2. Check swap status in `waagent.conf`.
        3. Verify that values in step 1 and step 2 are equal.
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Deployed,
        ),
    )
    def verify_swap(self, log: Logger, node: RemoteNode) -> None:
        swapon_output = node.tools[SwapOn].run("-s", sudo=True).stdout
        lsblk_output = node.tools[Lsblk].run().stdout
        _is_swap_enabled = self._is_swap_enabled(log, node)

        if (
            ("swap" in swapon_output) or ("SWAP" in lsblk_output)
        ) and not _is_swap_enabled:
            raise LisaException(
                "Swap is disabled in waagent.conf but swap partition/files found."
            )

        if (
            ("swap" not in swapon_output) and ("SWAP" not in lsblk_output)
        ) and _is_swap_enabled:
            raise LisaException(
                "Swap is enabled in waagent.conf but no swap partition/files found."
            )

    def _get_wala_conf_path(self, node: RemoteNode) -> str:
        if isinstance(node.os, CoreOs):
            return "/usr/share/oem/waagent.conf"
        elif node.os.information.vendor == "clear-linux-os":
            return "/usr/share/defaults/waagent/waagent.conf"
        else:
            return "/etc/waagent.conf"

    def _get_data_disk_mount_point(
        self,
        log: Logger,
        node: RemoteNode,
    ) -> str:
        if node.shell.exists(
            PurePosixPath("/var/log/cloud-init.log")
        ) and node.shell.exists(PurePosixPath("/var/lib/cloud/instance")):
            log.debug("Data handled by cloud-init.")
            mount_point = "/mnt"
        else:
            log.debug("ResourceDisk handled by waagent.")
            walacfg_path = self._get_wala_conf_path(node)
            walacfg = node.tools[Cat].run(walacfg_path).stdout
            matched = self._resource_disk_mount_point_regex.fullmatch(walacfg)
            assert matched
            mount_point = matched.group("resource_disk_mount_point")
        return mount_point

    def _get_os_disk_partition(
        self,
        log: Logger,
        node: RemoteNode,
    ) -> str:
        mount_output = node.tools[Mount].run().stdout
        os_disk_partition: Optional[str] = None
        for line in mount_output.splitlines():
            matched = self._root_partition_regex.fullmatch(line)
            if matched:
                os_disk_partition = matched.group("partition")
        assert os_disk_partition

        log.info(f"OS disk partition : {os_disk_partition}")
        return os_disk_partition

    def _is_swap_enabled(self, log: Logger, node: RemoteNode) -> bool:
        waagent_conf_file = self._get_wala_conf_path(node)
        walacfg = node.tools[Cat].run(waagent_conf_file).stdout
        matched = self._resource_disk_enable_swap_regex.fullmatch(walacfg)
        assert matched
        is_enabled = matched.group("resource_disk_enable_swap")
        if is_enabled == "y":
            return True
        elif is_enabled == "n":
            return False
        else:
            raise LisaException(
                f"Unknown value for ResourceDisk.EnableSwap : {is_enabled}"
            )
