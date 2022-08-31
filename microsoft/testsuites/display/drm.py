# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools import Cat
from lisa.operating_system import Redhat
from lisa.sut_orchestrator import AZURE, READY
from lisa.tools import Lsmod, Uname
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="drm",
    category="functional",
    description="""
    This test suite uses to verify drm driver sanity.
    """,
    requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
)
class Drm(TestSuite):
    @TestCaseMetadata(
        description="""
        This case is to check whether the hyperv_drm driver registered successfully.
        Once driver is registered successfully it should appear in `lsmod` output.

        Steps,
        1. lsmod
        2. Check if hyperv_drm exist in the list.
        """,
        priority=2,
    )
    def verify_drm_driver(self, node: Node, log: Logger) -> None:
        lsmod = node.tools[Lsmod]
        assert_that(lsmod.module_exists("hyperv_drm")).described_as(
            "hyperv_drm module is absent"
        ).is_equal_to(True)

    @TestCaseMetadata(
        description="""
        This case is to check whether the dri node is populated correctly.
        If hyperv_drm driver is bind correctly it should populate dri node.
        This dri node can be find at following sysfs entry : /sys/kernel/debug/dri/0.
        The dri node name (/sys/kernel/debug/dri/0/name) should contain `hyperv_drm`.

        Step,
        1. Cat /sys/kernel/debug/dri/0/name.
        2. Verify it contains hyperv_drm string in it.
        """,
        priority=2,
    )
    def verify_dri_node(self, node: Node, log: Logger) -> None:
        cat = node.tools[Cat]

        dri_path = "/sys/kernel/debug/dri/0/name"
        dri_name = cat.read(dri_path, sudo=True, force_run=True)
        assert_that(dri_name).described_as(
            "dri node not populated for hyperv_drm"
        ).matches("hyperv_drm")

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        kernel_version = node.tools[Uname].get_linux_information().kernel_version
        if (
            isinstance(node.os, Redhat)
            and node.os.information.version >= "9.0.0"
            and kernel_version > "5.13.0"
        ):
            log.debug("Currently only RHEL9 enables drm driver.")
        else:
            raise SkippedException("DRM hyperv driver is supported from 5.14.x kernel.")
