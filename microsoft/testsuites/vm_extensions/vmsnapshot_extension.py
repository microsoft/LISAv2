# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import time
import uuid
from datetime import datetime

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.sut_orchestrator.azure.common import get_compute_client
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="Test for VMSnapshot extension ",
    requirement=simple_requirement(unsupported_os=[]),
)
class BVTExtension(TestSuite):
    @TestCaseMetadata(
        description="""
        creates a restore point collection then a restore point which helps in
        validating the VMSnapshot extension.
        """,
        priority=1,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_vmsnapshot_extension(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        unique_name = str(uuid.uuid4())
        information = environment.get_information()
        resource_group_name = information["resource_group_name"]
        location = information["location"]
        vm_name = node.name
        log.info(f"information {information}")
        restore_point_collection = "rpc_" + unique_name
        assert environment.platform
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)
        sub_id = platform.subscription_id
        # creating restore point collection
        client = get_compute_client(environment.platform)
        response = client.restore_point_collections.create_or_update(
            resource_group_name=information["resource_group_name"],
            restore_point_collection_name=restore_point_collection,
            parameters={
                "location": location,
                "properties": {
                    "source": {
                        "id": "/subscriptions/"
                        + sub_id
                        + "/resourceGroups/"
                        + resource_group_name
                        + "/providers/Microsoft.Compute/virtualMachines/"
                        + vm_name
                    }
                },
            },
        )
        log.info("rpc created")
        log.info(f"response {response}")
        count = 0

        while count < 10:
            vm = client.virtual_machines.get(resource_group_name, vm_name)
            # check the state of the VM
            if vm.provisioning_state == "Succeeded":
                try:
                    # create a restore point for the VM
                    response = client.restore_points.begin_create(
                        resource_group_name=information["resource_group_name"],
                        restore_point_collection_name=restore_point_collection,
                        restore_point_name="rp_"
                        + datetime.now().strftime("%Y-%m-%d-%H-%M-%S"),
                        parameters={},
                    )
                    response.wait(3600)
                    log.info("restore point created")
                    break
                except Exception as e:
                    if "Changes were made to the Virtual Machine" in str(e):
                        pass
                    else:
                        log.info(f"error {e}")
                        raise AssertionError("Test failed: Unexpected error occurred")
            time.sleep(1)
            count = count + 1
        assert count < 10, "Failed in Creating Restore Point"
