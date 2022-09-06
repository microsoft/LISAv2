# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

from retry import retry

from lisa import (
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    UnsupportedDistroException,
)
from lisa.operating_system import Debian, Posix
from lisa.tools import Ping


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="""
    This test suite covers DNS name resolution functionality.
    """,
)
class Dns(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case check DNS name resolution by ping bing.com.
        """,
        priority=1,
    )
    def verify_dns_name_resolution(self, node: Node) -> None:
        self._check_dns_name_resolution(node)

    @TestCaseMetadata(
        description="""
        This test case check DNS name resolution by ping bing.com after upgrade system.
        """,
        priority=1,
    )
    def verify_dns_name_resolution_after_upgrade(self, node: Node) -> None:
        self._check_dns_name_resolution(node)
        if isinstance(node.os, Debian):
            node.execute(
                "apt update && unattended-upgrade -d -v",
                sudo=True,
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="fail to run unattended-upgrade",
            )
        elif isinstance(node.os, Posix):
            node.os.update_packages("")
        else:
            raise UnsupportedDistroException(node.os)
        self._check_dns_name_resolution(node)
        node.reboot()
        self._check_dns_name_resolution(node)

    @retry(tries=10, delay=0.5)
    def _check_dns_name_resolution(self, node: Node) -> None:
        ping = node.tools[Ping]
        ping.ping(target="bing.com")
