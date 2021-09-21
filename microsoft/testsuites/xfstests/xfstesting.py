# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa import (
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    simple_requirement,
)
from lisa.features import Disk, Nvme
from lisa.tools import Fdisk, Mkfs, Mount, Parted, Xfstests
from lisa.tools.mkfs import FileSystem

_scratch_folder = "/root/scratch"
_test_folder = "/root/test"


def _configure_disk(
    node: Node,
    disk_name: str,
    first_disk: str,
    second_disk: str,
    first_mountpoint: str = _test_folder,
    second_mountpoint: str = _scratch_folder,
    file_system: FileSystem = FileSystem.xfs,
) -> None:
    mount = node.tools[Mount]
    fdisk = node.tools[Fdisk]
    parted = node.tools[Parted]
    mkfs = node.tools[Mkfs]

    node.execute(f"rm -r {first_mountpoint}", sudo=True)
    node.execute(f"rm -r {second_mountpoint}", sudo=True)

    fdisk.delete_partitions(disk_name)

    mount.umount(first_disk, first_mountpoint)
    mount.umount(second_disk, second_mountpoint)

    parted.make_label(disk_name)
    parted.make_partition(disk_name, "primary", "1", "50%")
    parted.make_partition(disk_name, "secondary", "50%", "100%")

    mkfs.format_disk(first_disk, file_system)
    mkfs.format_disk(second_disk, file_system)

    node.execute(f"mkdir {first_mountpoint}", sudo=True)
    node.execute(f"mkdir {second_mountpoint}", sudo=True)


@TestSuiteMetadata(
    area="storage",
    category="community",
    description="""
    This test suite is to validate different types of data disk on Linux VM
     using xfstests.
    """,
)
class Xfstesting(TestSuite):
    # Use xfstests benchmark to test the different types of data disk,
    #  it will run many cases, so the runtime is longer than usual case.
    TIME_OUT = 7200

    @TestCaseMetadata(
        description="""
        This test case will run generic xfstests testing against
         standard data disk with xfs type system.
        """,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=1300,
                data_disk_count=1,
            ),
        ),
        timeout=TIME_OUT,
        priority=3,
    )
    def xfstesting_generic_standard_datadisk_validation(self, node: Node) -> None:
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            data_disks[0],
            f"{data_disks[0]}1",
            f"{data_disks[0]}2",
            excluded_tests="generic/430 generic/431 generic/434",
        )

    @TestCaseMetadata(
        description="""
        This test case will run xfs xfstests testing against
         standard data disk with xfs type system.
        """,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=1300,
                data_disk_count=1,
            ),
        ),
        timeout=TIME_OUT,
        priority=3,
    )
    def xfstesting_xfs_standard_datadisk_validation(self, node: Node) -> None:
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            data_disks[0],
            f"{data_disks[0]}1",
            f"{data_disks[0]}2",
            test_type=FileSystem.xfs.name,
            excluded_tests="generic/430 generic/431 generic/434",
        )

    @TestCaseMetadata(
        description="""
        This test case will run ext4 xfstests testing against
         standard data disk with ext4 type system.
        """,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=1300,
                data_disk_count=1,
            ),
        ),
        timeout=TIME_OUT,
        priority=3,
    )
    def xfstesting_ext4_standard_datadisk_validation(self, node: Node) -> None:
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            data_disks[0],
            f"{data_disks[0]}1",
            f"{data_disks[0]}2",
            file_system=FileSystem.ext4,
            test_type=FileSystem.ext4.name,
        )

    @TestCaseMetadata(
        description="""
        This test case will run btrfs xfstests testing against
         standard data disk with btrfs type system.
        """,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_iops=1300,
                data_disk_count=1,
            ),
        ),
        timeout=TIME_OUT,
        priority=3,
    )
    def xfstesting_btrfs_standard_datadisk_validation(self, node: Node) -> None:
        disk = node.features[Disk]
        data_disks = disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            data_disks[0],
            f"{data_disks[0]}1",
            f"{data_disks[0]}2",
            file_system=FileSystem.btrfs,
            test_type=FileSystem.btrfs.name,
            excluded_tests="btrfs/244",
        )

    @TestCaseMetadata(
        description="""
        This test case will run generic xfstests testing against
         nvme data disk with xfs type system.
        """,
        timeout=TIME_OUT,
        priority=3,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def xfstesting_generic_nvme_datadisk_validation(self, node: Node) -> None:
        nvme_disk = node.features[Nvme]
        nvme_data_disks = nvme_disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            nvme_data_disks[0],
            f"{nvme_data_disks[0]}p1",
            f"{nvme_data_disks[0]}p2",
            excluded_tests="generic/430 generic/431 generic/434",
        )

    @TestCaseMetadata(
        description="""
        This test case will run xfs xfstests testing against
         nvme data disk with xfs type system.
        """,
        timeout=TIME_OUT,
        priority=3,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def xfstesting_xfs_nvme_datadisk_validation(self, node: Node) -> None:
        nvme_disk = node.features[Nvme]
        nvme_data_disks = nvme_disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            nvme_data_disks[0],
            f"{nvme_data_disks[0]}p1",
            f"{nvme_data_disks[0]}p2",
            test_type=FileSystem.xfs.name,
        )

    @TestCaseMetadata(
        description="""
        This test case will run ext4 xfstests testing against
         nvme data disk with ext4 type system.
        """,
        timeout=TIME_OUT,
        priority=3,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def xfstesting_ext4_nvme_datadisk_validation(self, node: Node) -> None:
        nvme_disk = node.features[Nvme]
        nvme_data_disks = nvme_disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            nvme_data_disks[0],
            f"{nvme_data_disks[0]}p1",
            f"{nvme_data_disks[0]}p2",
            file_system=FileSystem.ext4,
            test_type=FileSystem.ext4.name,
        )

    @TestCaseMetadata(
        description="""
        This test case will run btrfs xfstests testing against
         nvme data disk with btrfs type system.
        """,
        timeout=TIME_OUT,
        priority=3,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def xfstesting_btrfs_nvme_datadisk_validation(self, node: Node) -> None:
        nvme_disk = node.features[Nvme]
        nvme_data_disks = nvme_disk.get_raw_data_disks()
        self._execute_xfstests(
            node,
            nvme_data_disks[0],
            f"{nvme_data_disks[0]}p1",
            f"{nvme_data_disks[0]}p2",
            file_system=FileSystem.btrfs,
            test_type=FileSystem.btrfs.name,
            excluded_tests="btrfs/244",
        )

    def _execute_xfstests(
        self,
        node: Node,
        data_disk: str,
        test_dev: str,
        scratch_dev: str,
        file_system: FileSystem = FileSystem.xfs,
        test_type: str = "generic",
        excluded_tests: str = "",
    ) -> None:
        _configure_disk(node, data_disk, test_dev, scratch_dev, file_system=file_system)
        xfstests = node.tools[Xfstests]
        xfstests.set_local_config(scratch_dev, _scratch_folder, test_dev)
        xfstests.set_excluded_tests(excluded_tests)
        node.execute(
            f"export TEST_DIR={_test_folder} && "
            f"bash check -g {test_type}/quick -E exclude.txt",
            sudo=True,
            shell=True,
            cwd=xfstests.get_xfstests_path(),
            timeout=self.TIME_OUT,
        )
