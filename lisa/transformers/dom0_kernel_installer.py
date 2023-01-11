# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import List, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.node import Node
from lisa.tools import Cp, Sed, Uname
from lisa.util import field_metadata

from .kernel_installer import BaseInstaller, BaseInstallerSchema
from .kernel_source_installer import SourceInstaller, SourceInstallerSchema


@dataclass_json()
@dataclass
class BinaryInstallerSchema(BaseInstallerSchema):

    # kernel binary local absolute path
    kernel_image_path: str = field(
        default="",
        metadata=field_metadata(
            required=True,
        ),
    )

    # initrd binary local absolute path
    initrd_image_path: str = field(
        default="",
        metadata=field_metadata(
            required=False,
        ),
    )


class BinaryInstaller(BaseInstaller):
    @classmethod
    def type_name(cls) -> str:
        return "dom0_binaries"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return BinaryInstallerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def validate(self) -> None:
        # nothing to validate before source installer started.
        ...

    def install(self) -> str:
        node = self._node
        runbook: BinaryInstallerSchema = self.runbook
        kernel_image_path: str = runbook.kernel_image_path
        initrd_image_path: str = runbook.initrd_image_path
        is_initrd: bool = False

        uname = node.tools[Uname]
        current_kernel = uname.get_linux_information().kernel_version_raw

        # Kernel absolute path: /home/user/vmlinuz-5.15.57.1+
        # Naming convention : vmlinuz-<version>
        new_kernel = os.path.basename(kernel_image_path).split("-")[1].strip()

        # Copy the binaries to azure VM from where LISA is running
        err: str = f"Can not find kernel image path: {kernel_image_path}"
        assert os.path.exists(kernel_image_path), err
        node.shell.copy(
            PurePath(kernel_image_path),
            node.get_pure_path(f"/var/tmp/vmlinuz-{new_kernel}"),
        )

        if initrd_image_path:
            err = f"Can not find initrd image path: {initrd_image_path}"
            assert os.path.exists(initrd_image_path), err
            is_initrd = True
            node.shell.copy(
                PurePath(initrd_image_path),
                node.get_pure_path(f"/var/tmp/initrd.img-{new_kernel}"),
            )

        _copy_kernel_binary(
            node,
            is_initrd,
            node.get_pure_path(f"/var/tmp/vmlinuz-{new_kernel}"),
            node.get_pure_path(f"/boot/efi/vmlinuz-{new_kernel}"),
            node.get_pure_path(f"/var/tmp/initrd.img-{new_kernel}"),
            node.get_pure_path(f"/boot/efi/initrd.img-{new_kernel}"),
        )

        _update_linux_loader(
            node,
            is_initrd,
            current_kernel,
            new_kernel,
        )

        return new_kernel


class Dom0Installer(SourceInstaller):
    @classmethod
    def type_name(cls) -> str:
        return "dom0"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SourceInstallerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def install(self) -> str:
        node = self._node
        new_kernel = super().install()

        # If it is dom0,
        # Name of the current kernel binary should be vmlinuz-<kernel version>
        uname = node.tools[Uname]
        current_kernel = uname.get_linux_information().kernel_version_raw

        # Copy the kernel to /boot/efi from /boot
        # Copy the new initrd to /boot/efi from /boot
        # Here super.install() will create new initrd/kernel binary at /boot
        _copy_kernel_binary(
            node,
            True,
            node.get_pure_path(f"/boot/vmlinuz-{new_kernel}"),
            node.get_pure_path(f"/boot/efi/vmlinuz-{new_kernel}"),
            node.get_pure_path(f"/boot/initrd.img-{new_kernel}"),
            node.get_pure_path(f"/boot/efi/initrd.img-{new_kernel}"),
        )

        _update_linux_loader(
            node,
            True,
            current_kernel,
            new_kernel,
        )

        return new_kernel


def _copy_kernel_binary(
    node: Node,
    is_initrd: bool,
    kernel_source: PurePath,
    kernel_dest: PurePath,
    initrd_source: PurePath,
    initrd_dest: PurePath,
) -> None:
    cp = node.tools[Cp]
    cp.copy(
        src=kernel_source,
        dest=kernel_dest,
        sudo=True,
    )
    if is_initrd:
        cp.copy(
            src=initrd_source,
            dest=initrd_dest,
            sudo=True,
        )


def _update_linux_loader(
    node: Node,
    is_initrd: bool,
    current_kernel: str,
    new_kernel: str,
) -> None:

    ll_conf_file: str = "/boot/efi/linuxloader.conf"
    sed = node.tools[Sed]

    # Modify the linuxloader.conf to point new kernel binary
    sed.substitute(
        regexp=f"KERNEL_PATH=vmlinuz-{current_kernel}",
        replacement=f"KERNEL_PATH=vmlinuz-{new_kernel}",
        file=ll_conf_file,
        sudo=True,
    )

    if is_initrd:
        # Modify the linuxloader.conf to point new initrd binary
        sed.substitute(
            regexp=f"INITRD_PATH=initrd.img-{current_kernel}",
            replacement=f"INITRD_PATH=initrd.img-{new_kernel}",
            file=ll_conf_file,
            sudo=True,
        )
