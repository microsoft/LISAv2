# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import List, Type, cast

from lisa.executable import Tool
from lisa.operating_system import Debian, Fedora, Posix
from lisa.tools import Echo

from .git import Git
from .make import Make


class Xfstests(Tool):
    repo = "https://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git"
    debian_dep = [
        "xfslibs-dev",
        "uuid-dev",
        "libtool-bin",
        "e2fsprogs",
        "automake",
        "libuuid1",
        "quota",
        "attr",
        "libacl1-dev",
        "libaio-dev",
        "xfsprogs",
        "libgdbm-dev",
        "gawk",
        "fio",
        "dbench",
        "uuid-runtime",
        "python",
        "sqlite3",
    ]
    fedora_dep = [
        "acl",
        "attr",
        "automake",
        "bc",
        "dbench",
        "dump",
        "e2fsprogs",
        "fio",
        "gawk",
        "indent",
        "libtool",
        "lvm2",
        "psmisc",
        "quota",
        "sed",
        "xfsdump",
        "xfsprogs",
        "libacl-devel",
        "libaio-devel",
        "libuuid-devel",
        "xfsprogs-devel",
        "btrfs-progs-devel",
        "python",
        "sqlite",
        "libcap-devel",
        "liburing-dev",
    ]

    @property
    def command(self) -> str:
        return "xfstests"

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Make]

    def _install_dep(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        tool_path = self.get_tool_path()
        self.node.shell.mkdir(tool_path, exist_ok=True)
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path)
        # install dependency packages
        if isinstance(self.node.os, Fedora):
            posix_os.install_packages(list(self.fedora_dep))
        elif isinstance(self.node.os, Debian):
            posix_os.install_packages(list(self.debian_dep))

    def _add_test_users(self) -> None:
        self.node.execute("useradd -m fsgqa", sudo=True)
        self.node.execute("groupadd fsgqa", sudo=True)
        self.node.execute("useradd 123456-fsgqa", sudo=True)
        self.node.execute("useradd fsgqa2", sudo=True)

    def _install(self) -> bool:
        self._add_test_users()
        self._install_dep()
        tool_path = self.get_tool_path()
        make = self.node.tools[Make]
        code_path = tool_path.joinpath("xfstests-dev")
        make.make_install(code_path)
        return True

    def get_xfstests_path(self) -> PurePath:
        tool_path = self.get_tool_path()
        return tool_path.joinpath("xfstests-dev")

    def set_local_config(
        self, scratch_dev: str, scratch_mnt: str, test_dev: str
    ) -> None:
        xfstests_path = self.get_xfstests_path()
        config_path = xfstests_path.joinpath("local.config")
        echo = self.node.tools[Echo]
        echo.write_to_file(f"SCRATCH_DEV={scratch_dev}", str(config_path), sudo=True)
        echo.write_to_file(
            f"SCRATCH_MNT={scratch_mnt}", str(config_path), append=True, sudo=True
        )
        echo.write_to_file(
            f"TEST_DEV={test_dev}", str(config_path), append=True, sudo=True
        )

    def set_excluded_tests(self, exclude_tests: str) -> None:
        if exclude_tests:
            xfstests_path = self.get_xfstests_path()
            exclude_file_path = xfstests_path.joinpath("exclude.txt")
            echo = self.node.tools[Echo]
            echo.write_to_file(exclude_tests, str(exclude_file_path), sudo=True)
