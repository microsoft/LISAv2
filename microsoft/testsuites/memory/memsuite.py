# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Any, Dict

from assertpy import fail
from retry import retry

from lisa import (
    BadEnvironmentStateException,
    RemoteNode,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.operating_system import Debian, Fedora
from lisa.tools import Wget

SCRIPT_NAME = "install_script.sh"
PERCENTILE_CHECKER = re.compile(r"95th percentile:\s+(?P<percent_data>[0-9.]+)")


@TestSuiteMetadata(
    area="memory",
    category="functional",
    description="""
    This test suite runs a basic memory access latency check.
    """,
)
class Memory(TestSuite):
    @TestCaseMetadata(
        description="""
        run a test to measure the memory latency of the node
        """,
        priority=1,
    )
    def verify_memory_latency(
        self, node: RemoteNode, variables: Dict[str, Any]
    ) -> None:
        wget = node.tools[Wget]
        if isinstance(node.os, Debian):
            pkg_type = "deb"
        elif isinstance(node.os, Fedora):
            pkg_type = "rpm"
        else:
            raise SkippedException(
                "This OS is not supported by the memory latency test."
            )

        # http can fail so make a lil function to retry a few times
        @retry(tries=5, delay=10)
        def resilient_wget() -> None:
            wget.get(
                (
                    "https://packagecloud.io/install/repositories/"
                    f"akopytov/sysbench/script.{pkg_type}.sh"
                ),
                filename=SCRIPT_NAME,
                executable=True,
            )

        resilient_wget()

        # need to update before install
        node.os.update_packages("")
        result = node.execute(
            f"{node.working_path.joinpath(SCRIPT_NAME)}",
            shell=True,
            sudo=True,
        )

        if result.exit_code != 0:
            node.log.info(
                "Sysbench repository/dependency script failed. Will attempt package manager install."
            )

        node.os.install_packages("sysbench")

        sysbench_result = node.execute(
            (
                "sysbench memory  --memory-access-mode=rnd "
                "--memory-total-size=4G --memory-block-size=512M run"
            )
        )

        percentile_match = PERCENTILE_CHECKER.search(sysbench_result.stdout)
        if percentile_match:
            percent_data = percentile_match.group("percent_data")
            if percent_data:
                if float(percent_data) > 3500.0:
                    fail(
                        (
                            "Latency test failed with loaded latency measurement: "
                            f"{percent_data} (expected under 3500ms)"
                        )
                    )
                else:
                    node.log.info(
                        f"Latency check passed, found latency: {percent_data}"
                    )
            else:
                fail("Could not find latency data in sysbench output!")
