# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from urllib.parse import urlparse

from assertpy import fail

from lisa import Node
from lisa.features import Disk
from lisa.operating_system import Debian, Fedora, Suse
from lisa.tools import Chmod, Gcc, Git, Make, Pkgconfig, Tar, Wget
from lisa.util import LisaException, SkippedException


class RdmaCoreManager:
    def __init__(self, node: Node, rdma_core_source: str, rdma_core_ref: str,
            update_kernel: bool) -> None:
        self.is_installed_from_source = False
        self.node = node
        self._rdma_core_source = rdma_core_source
        self._rdma_core_ref = rdma_core_ref
        # add space if none is available
        build_location = node.get_working_path_with_required_space(10)
        if not build_location:
            node.features[Disk].add_data_disk(count=1, size_in_gb=20)
            build_location = node.get_working_path_with_required_space(10)
        assert build_location, "Could not find a location to build rdma-core"
        self._build_location = node.get_pure_path(build_location).joinpath("rdma")

        self.update_kernel = update_kernel

    def get_missing_distro_packages(self) -> str:
        distro = self.node.os
        package = ""
        # check if rdma-core is installed already...
        if self.node.tools[Pkgconfig].package_info_exists("libibuverbs"):
            return package
        if isinstance(distro, Debian):
            package = "rdma-core ibverbs-providers libibverbs-dev"
        elif isinstance(distro, Suse):
            package = "rdma-core-devel librdmacm1"
        elif isinstance(distro, Fedora):
            package = "librdmacm-devel"
        else:
            fail("Invalid OS for rdma-core source installation.")
        return package

    def _check_source_name(self) -> bool:
        source = self._rdma_core_source
        try:
            parts = urlparse(self._rdma_core_source)
        except ValueError:
            raise LisaException(f"Invalid rdma-core source build url: {source}")
        file_path = parts.path.split("/")[-1]
        return (
            any([parts.scheme == x for x in ["https", "ssh"]])
            and parts.netloc != ""
            and (
                file_path == "rdma-core.git"
                or (file_path.startswith("rdma-core") and file_path.endswith(".tar.gz"))
            )
        )

    _rdma_core_domain_pattern = re.compile(
        (
            r"^((?:www\.)?(?:(?:(?:microsoft|msazure)\.)"
            r"?(?:visualstudio|gitlab|github)\.com)|git\.launchpad\.net)"
        )
    )
    _source_pattern = re.compile(r"rdma-core(.v?[0-9]+)*.(git|tar(\.gz)?)")

    def _check_source_install(self) -> None:
        if self._rdma_core_source:
            # accept either a tar.gz or a git tree
            if self.is_from_tarball():
                self._rdma_core_ref = ""
            elif self.is_from_git():
                # will check ref later
                pass
            else:
                raise SkippedException(
                    "rdma-core source must be rdma-core.*tar.gz "
                    f"or https://.../rdma-core.git. found {self._rdma_core_source}"
                )
        elif self._rdma_core_ref:
            # if there's a ref but no tree, use a default tree
            self._rdma_core_source = "https://github.com/linux-rdma/rdma-core.git"
        else:
            # no ref, no tree, use a default tar.gz
            self._rdma_core_source = (
                "https://github.com/linux-rdma/rdma-core/"
                "releases/download/v46.0/rdma-core-46.0.tar.gz"
            )

        self.is_installed_from_source = True

    def _get_source_pkg_error_message(self) -> str:
        return (
            "rdma-source package provided did not validate. "
            "Use https for a git named rdma-core.git or "
            "https/sftp to fetch a tar.gz package named rdma-core(.xx).tar.gz. "
            "Source site must be at visualstudio, gitlab, github, or git.launchpad.net."
            f"Found: {self._rdma_core_source}"
        )

    def is_from_git(self) -> bool:
        return bool(
            self._rdma_core_source and self._rdma_core_source.endswith("rdma-core.git")
        )

    def is_from_tarball(self) -> bool:
        return bool(
            self._rdma_core_source and self._rdma_core_source.endswith(".tar.gz")
        )

    def can_install_from_source(self) -> bool:
        return bool(self._rdma_core_source or self._rdma_core_ref)

    def do_source_install(self) -> None:
        node = self.node
        wget = node.tools[Wget]
        make = node.tools[Make]
        tar = node.tools[Tar]
        distro = node.os

        # avoid second build
        if (
            node.execute("test -f /.rdma-core-built", shell=True, sudo=True).exit_code
            == 0
        ):
            return

        # setup looks at options and selects some reasonable defaults
        # allow a tar.gz or git
        # if ref and no tree, use the default tree at github
        # if tree and no ref, checkout latest tag
        # if tree and ref... you get the idea
        self._check_source_install()

        # for dependencies, see https://github.com/linux-rdma/rdma-core#building
        if isinstance(distro, Debian):
            distro.install_packages(
                [
                    Pkgconfig,
                    "cmake",
                    "libudev-dev",
                    "libnl-3-dev",
                    "libnl-route-3-dev",
                    "ninja-build",
                    "valgrind",
                    "python3-dev",
                    "cython3",
                    "python3-docutils",
                    "pandoc",
                    "libssl-dev",
                    "libelf-dev",
                    "python3-pip",
                    "libnuma-dev",
                ]
            )
        elif isinstance(distro, Fedora):
            distro.group_install_packages("Development Tools")
            distro.install_packages(
                [
                    Gcc,
                    Pkgconfig,
                    Tar,
                    Wget,
                    "cmake",
                    "libudev-devel",
                    "libnl3-devel",
                    "valgrind",
                    "python3-devel",
                    "python3-docutils",
                    "openssl-devel",
                    "unzip",
                    "elfutils-devel",
                    "python3-pip",
                    "libpcap-devel",
                    "dos2unix",
                    "psmisc",
                    "librdmacm-devel",
                    "libmnl-devel",
                    "numactl-devel",
                    "elfutils-libelf-devel",
                    "meson",
                    "ninja-build",
                    "libbpf-devel",
                ]
            )
            if self.update_kernel:
                distro.install_packages(
                    [
                        "kernel-devel",
                        "kernel-modules-extra",
                        "kernel-headers",
                    ]
                )
        else:
            # no-op, throw for invalid distro is before this function
            return

        if self.is_from_git():
            git = node.tools[Git]
            source_path = git.clone(
                self._rdma_core_source,
                cwd=self._build_location,
                ref=self._rdma_core_ref,
            )

            # if there wasn't a ref provided, check out the latest tag
            if not self._rdma_core_ref:
                git_ref = git.get_tag(cwd=source_path)
                git.checkout(git_ref, cwd=source_path)
        elif self.is_from_tarball():
            tar_path = wget.get(
                url=(self._rdma_core_source),
                file_path=str(self._build_location),
            )

            tar.extract(
                tar_path, dest_dir=str(self._build_location), gzip=True, sudo=True
            )
            source_folder = tar_path.replace(".tar.gz", "")
            source_path = node.get_pure_path(source_folder)
        else:
            raise SkippedException(self._get_source_pkg_error_message())

        node.execute(
            "cmake -DIN_PLACE=0 -DNO_MAN_PAGES=1 -DCMAKE_INSTALL_PREFIX=/usr",
            shell=True,
            cwd=source_path,
            sudo=True,
            no_debug_log=True,
            no_info_log=True,
        )
        make.make_install(source_path)
        node.execute("touch /.rdma-core-built", shell=True, sudo=True)
