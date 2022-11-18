# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List, Type

from lisa import features
from lisa.environment import Environment
from lisa.feature import Feature
from lisa.platform_ import Platform
from lisa.util.logger import Logger

from . import READY


class ReadyPlatform(Platform):
    @classmethod
    def type_name(cls) -> str:
        return READY

    @classmethod
    def supported_features(cls) -> List[Type[Feature]]:
        return [
            features.Disk,
            features.Gpu,
            features.Nvme,
            features.NestedVirtualization,
            features.NetworkInterface,
            features.Infiniband,
            features.Hibernation,
            features.IsolatedResource,
            features.Nfs,
        ]

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        if environment.runbook.nodes_requirement:
            log.warn_or_raise(
                environment.warn_as_error,
                "ready platform cannot process environment with requirement",
            )
        is_success: bool = False
        if len(environment.nodes):
            # if it has nodes, it's a good environment to run test cases
            is_success = True
        return is_success

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        # do nothing for deploy
        pass

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        # ready platform doesn't support delete environment
        pass
