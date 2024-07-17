# Copyright (c) Microsoft Corporation. Licensed under the MIT license.

from typing import Any

from assertpy.assertpy import assert_that
from azure.core.exceptions import HttpResponseError

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools.service import Service
from lisa.operating_system import BSD, SLES, CBLMariner, Ubuntu
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    get_compute_client,
    get_node_context,
    wait_operation,
)
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.util import SkippedException, UnsupportedDistroException


def _verify_unsupported_images(node: Node) -> None:
    # Unsupported detailed versions for x86_64
    unsupported_versions_x86_64 = {
        SLES: ["15-sp5 gen1"],
        CBLMariner: ["2"],
    }

    # arch = node.os.get_kernel_information().hardware_platform  # type: ignore
    # if arch == "aarch64":
    #     # Any arm64 OS images are not supported at this time
    #     _unsupported_image_exception_msg(node)

    # Get the full version string of the OS
    full_version = (
        f"{node.os.information.version.major}-"
        f"{node.os.information.version.minor} "
        f"{node.os.information.version.patch} "
        f"{node.os.information.version.build}"
    )

    # Handle CBLMariner separately if the full version string is not sufficient
    if isinstance(node.os, CBLMariner):
        full_version = str(node.os.information.version.major)

    for distro in unsupported_versions_x86_64:
        if isinstance(node.os, distro):
            version_list = unsupported_versions_x86_64.get(distro)
            if version_list is not None and full_version in version_list:
                # Raise an exception for unsupported version
                _unsupported_image_exception_msg(node)


def _verify_unsupported_vm_agent(
    node: Node, status_result: Any, error_code: str
) -> None:
    if (
        error_code == "1"
        and "Unsupported older Azure Linux Agent version"
        in status_result["error"]["details"][0]["message"]
    ):
        _unsupported_image_exception_msg(node)


def _set_up_vm(node: Node, environment: Environment) -> Any:
    assert environment.platform, "platform shouldn't be None."
    platform: AzurePlatform = environment.platform  # type: ignore
    assert isinstance(
        platform, AzurePlatform
    ), "platform should be AzurePlatform instance"
    assert isinstance(
        platform, AzurePlatform
    ), "platform should be AzurePlatform instance"
    compute_client = get_compute_client(platform)
    node_context = get_node_context(node)
    resource_group_name = node_context.resource_group_name
    vm_name = node_context.vm_name

    return compute_client, resource_group_name, vm_name


def _verify_vm_agent_running(node: Node, log: Logger) -> None:
    service = node.tools[Service]
    is_vm_agent_running = service.is_service_running(
        "walinuxagent"
    ) or service.is_service_running("waagent")

    log.debug(f"verify walinuxagent or waagent running:{is_vm_agent_running}")

    assert_that(is_vm_agent_running).described_as(
        "Expected walinuxagent or waagent service is running"
    ).is_true()


def _assert_status_file_result(node: Node, status_file: Any, error_code: str) -> None:
    error_details_not_empty = len(status_file["error"]["details"]) > 0
    if (
        error_details_not_empty
        and status_file["error"]["details"][0]["code"] == "PACKAGE_LIST_TRUNCATED"
    ):
        assert_that(status_file["status"]).described_as(
            "Expected the status file patches to CompletedWithWarnings"
        ).is_equal_to("CompletedWithWarnings")
    elif (
        _is_supported_linux_distro(node)
        and error_details_not_empty
        and status_file["error"]["details"][0]["code"] == "UA_ESM_REQUIRED"
    ):
        # Ubuntu 1804 OS image has UA patches that needs upgrade OS to Pro version
        # Set error code to 1 notify customers to upgrade OS to Pro to install patches
        assert_that(status_file["status"]).described_as(
            "Expected the status file patches to succeed"
        ).is_equal_to("Succeeded")
        assert_that(error_code).described_as(
            "Expected 1 error in status file patches operation"
        ).is_equal_to("1")

    else:
        assert_that(status_file["status"]).described_as(
            "Expected the status file patches to succeed"
        ).is_equal_to("Succeeded")

        assert_that(error_code).described_as(
            "Expected no error in status file patches operation"
        ).is_equal_to("0")


def _is_supported_linux_distro(node: Node) -> bool:
    supported_major_versions = {
        Ubuntu: [18],
    }

    for distro in supported_major_versions:
        if isinstance(node.os, distro):
            version_list = supported_major_versions.get(distro)
            if (
                version_list is not None
                and node.os.information.version.major in version_list
            ):
                return True
            else:
                return False
    return False


def _unsupported_image_exception_msg(node: Node) -> None:
    raise SkippedException(
        UnsupportedDistroException(
            node.os, "Linux Patch Extension doesn't support this Distro version."
        )
    )


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="Test for Linux Patch Extension",
    requirement=simple_requirement(
        supported_platform_type=[AZURE], unsupported_os=[BSD]
    ),
)
class LinuxPatchExtensionBVT(TestSuite):
    TIMEOUT = 14400  # 4H Max install operation duration

    @TestCaseMetadata(
        description="""
        Verify walinuxagent or waagent service is running on vm. Perform assess
        patches to trigger Microsoft.CPlat.Core.LinuxPatchExtension creation in
        vm. Verify status file response for validity.
        """,
        priority=1,
        timeout=600,
    )
    def verify_vm_assess_patches(
        self, node: Node, environment: Environment, log: Logger
    ) -> None:
        compute_client, resource_group_name, vm_name = _set_up_vm(node, environment)
        _verify_unsupported_images(node)
        # verify vm agent service is running, lpe is a dependent of vm agent
        # service
        _verify_vm_agent_running(node, log)

        try:
            operation = compute_client.virtual_machines.begin_assess_patches(
                resource_group_name=resource_group_name, vm_name=vm_name
            )
            # set wait operation timeout 10 min, status file should be generated
            # before timeout
            assess_result = wait_operation(operation)

        except HttpResponseError as identifier:
            if any(
                s in str(identifier) for s in ["The selected VM image is not supported"]
            ):
                _unsupported_image_exception_msg(node)
            else:
                raise identifier

        assert assess_result, "assess_result shouldn't be None"
        log.debug(f"assess_result:{assess_result}")
        error_code = assess_result["error"]["code"]

        _verify_unsupported_vm_agent(node, assess_result, error_code)
        _assert_status_file_result(node, assess_result, error_code)

    @TestCaseMetadata(
        description="""
        Verify walinuxagent or waagent service is running on vm. Perform install
        patches to trigger Microsoft.CPlat.Core.LinuxPatchExtension creation in vm.
        Verify status file response for validity.
        """,
        priority=3,
        timeout=TIMEOUT,
    )
    def verify_vm_install_patches(
        self, node: Node, environment: Environment, log: Logger
    ) -> None:
        compute_client, resource_group_name, vm_name = _set_up_vm(node, environment)
        install_patches_input = {
            "maximumDuration": "PT4H",
            "rebootSetting": "IfRequired",
            "linuxParameters": {
                "classificationsToInclude": ["Security", "Critical"],
                "packageNameMasksToInclude": ["ca-certificates*", "php7-openssl*"],
            },
        }
        _verify_unsupported_images(node)
        # verify vm agent service is running, lpe is a dependent of vm agent
        # service
        _verify_vm_agent_running(node, log)

        try:
            operation = compute_client.virtual_machines.begin_install_patches(
                resource_group_name=resource_group_name,
                vm_name=vm_name,
                install_patches_input=install_patches_input,
            )
            # set wait operation max duration 4H timeout, status file should be
            # generated before timeout
            install_result = wait_operation(operation, self.TIMEOUT)

        except HttpResponseError as identifier:
            if any(
                s in str(identifier) for s in ["The selected VM image is not supported"]
            ):
                _unsupported_image_exception_msg(node)
            else:
                raise identifier

        assert install_result, "install_result shouldn't be None"
        log.debug(f"install_result:{install_result}")
        error_code = install_result["error"]["code"]

        _verify_unsupported_vm_agent(node, install_result, error_code)
        _assert_status_file_result(node, install_result, error_code)
