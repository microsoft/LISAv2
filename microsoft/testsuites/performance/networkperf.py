# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from functools import partial
from typing import Any, List, Tuple, cast

from lisa import (
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    node_requirement,
    schema,
    search_space,
    simple_requirement,
)
from lisa.environment import Environment, Node
from lisa.features import Sriov, Synthetic
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import CLOUD_HYPERVISOR
from lisa.sut_orchestrator.libvirt.context import get_node_context
from lisa.testsuite import TestResult
from lisa.tools import Lspci, Sysctl
from lisa.tools.iperf3 import (
    IPERF_TCP_BUFFER_LENGTHS,
    IPERF_TCP_CONCURRENCY,
    IPERF_UDP_BUFFER_LENGTHS,
    IPERF_UDP_CONCURRENCY,
)
from lisa.tools.sockperf import SOCKPERF_TCP, SOCKPERF_UDP
from lisa.util import SkippedException, constants, find_group_in_lines
from lisa.util.parallel import run_in_parallel
from microsoft.testsuites.performance.common import (
    cleanup_process,
    perf_iperf,
    perf_ntttcp,
    perf_sockperf,
    perf_tcp_latency,
    perf_tcp_pps,
)


@TestSuiteMetadata(
    area="network",
    category="performance",
    description="""
    This test suite is to validate linux network performance.
    """,
)
class NetworkPerformace(TestSuite):
    TIMEOUT = 12000
    PPS_TIMEOUT = 3000

    @TestCaseMetadata(
        description="""
        This test case uses lagscope to test synthetic network latency.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_latency_synthetic(self, result: TestResult) -> None:
        perf_tcp_latency(result)

    @TestCaseMetadata(
        description="""
        This test case uses lagscope to test sriov network latency.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_tcp_latency_sriov(self, result: TestResult) -> None:
        perf_tcp_latency(result)

    @TestCaseMetadata(
        description="""
        This test case uses sar to test synthetic network PPS (Packets Per Second)
         when running netperf with single port.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_single_pps_synthetic(self, result: TestResult) -> None:
        perf_tcp_pps(result, "singlepps")

    @TestCaseMetadata(
        description="""
        This test case uses sar to test sriov network PPS (Packets Per Second)
         when running netperf with single port.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_tcp_single_pps_sriov(self, result: TestResult) -> None:
        perf_tcp_pps(result, "singlepps")

    @TestCaseMetadata(
        description="""
        This test case uses sar to test synthetic network PPS (Packets Per Second)
         when running netperf with multiple ports.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_max_pps_synthetic(self, result: TestResult) -> None:
        perf_tcp_pps(result, "maxpps")

    @TestCaseMetadata(
        description="""
        This test case uses sar to test sriov network PPS (Packets Per Second)
         when running netperf with multiple ports.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_tcp_max_pps_sriov(self, result: TestResult) -> None:
        perf_tcp_pps(result, "maxpps")

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test synthetic tcp network throughput for
         128 connections.
        """,
        priority=2,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_ntttcp_128_connections_synthetic(self, result: TestResult) -> None:
        perf_ntttcp(result, connections=[128])

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test synthetic tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                memory_mb=search_space.IntRange(min=8192),
                network_interface=Synthetic(),
            )
        ),
    )
    def perf_tcp_ntttcp_synthetic(self, result: TestResult) -> None:
        perf_ntttcp(result)

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test sriov tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                memory_mb=search_space.IntRange(min=8192),
                network_interface=Sriov(),
            )
        ),
    )
    def perf_tcp_ntttcp_sriov(self, result: TestResult) -> None:
        perf_ntttcp(result)

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test synthetic udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_udp_1k_ntttcp_synthetic(self, result: TestResult) -> None:
        perf_ntttcp(result, udp_mode=True)

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test sriov udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_udp_1k_ntttcp_sriov(self, result: TestResult) -> None:
        perf_ntttcp(result, udp_mode=True)

    @TestCaseMetadata(
        description="""
        This test case uses iperf3 to test synthetic tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_iperf_synthetic(self, result: TestResult) -> None:
        perf_iperf(
            result,
            connections=IPERF_TCP_CONCURRENCY,
            buffer_length_list=IPERF_TCP_BUFFER_LENGTHS,
        )

    @TestCaseMetadata(
        description="""
        This test case uses iperf3 to test sriov tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_tcp_iperf_sriov(self, result: TestResult) -> None:
        perf_iperf(
            result,
            connections=IPERF_TCP_CONCURRENCY,
            buffer_length_list=IPERF_TCP_BUFFER_LENGTHS,
        )

    @TestCaseMetadata(
        description="""
        This test case uses iperf to test synthetic udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_udp_iperf_synthetic(self, result: TestResult) -> None:
        perf_iperf(
            result,
            connections=IPERF_UDP_CONCURRENCY,
            buffer_length_list=IPERF_UDP_BUFFER_LENGTHS,
            udp_mode=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses iperf to test sriov udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_udp_iperf_sriov(self, result: TestResult) -> None:
        perf_iperf(
            result,
            connections=IPERF_UDP_CONCURRENCY,
            buffer_length_list=IPERF_UDP_BUFFER_LENGTHS,
            udp_mode=True,
        )

    # Marked all following tests to skip on BSD since
    # sockperf compilation is not natively supported at this time
    # This is due to the default compiler on freebsd being c++17
    # and sockperf is designed to compile on c+11 which is no longer available
    # This is a way to compile it but it requires adding a patch file
    # to the sockperf repo to remove references to std::unary and std::binary
    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test sriov network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_sockperf_latency_tcp_sriov(self, result: TestResult) -> None:
        perf_sockperf(result, SOCKPERF_TCP, "perf_sockperf_latency_tcp_sriov")

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test sriov network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_sockperf_latency_udp_sriov(self, result: TestResult) -> None:
        perf_sockperf(result, SOCKPERF_UDP, "perf_sockperf_latency_udp_sriov")

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test synthetic network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_sockperf_latency_udp_synthetic(self, result: TestResult) -> None:
        perf_sockperf(result, SOCKPERF_UDP, "perf_sockperf_latency_udp_synthetic")

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test synthetic network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_sockperf_latency_tcp_synthetic(self, result: TestResult) -> None:
        perf_sockperf(result, SOCKPERF_TCP, "perf_sockperf_latency_tcp_synthetic")

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test sriov network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_sockperf_latency_tcp_sriov_busy_poll(self, result: TestResult) -> None:
        perf_sockperf(
            result,
            SOCKPERF_TCP,
            "perf_sockperf_latency_tcp_sriov_busy_poll",
            set_busy_poll=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test sriov network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_sockperf_latency_udp_sriov_busy_poll(self, result: TestResult) -> None:
        perf_sockperf(
            result,
            SOCKPERF_UDP,
            "perf_sockperf_latency_udp_sriov_busy_poll",
            set_busy_poll=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test synthetic network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_sockperf_latency_udp_synthetic_busy_poll(self, result: TestResult) -> None:
        perf_sockperf(
            result,
            SOCKPERF_UDP,
            "perf_sockperf_latency_udp_synthetic_busy_poll",
            set_busy_poll=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sockperf to test synthetic network latency.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
            unsupported_os=[BSD, Windows],
        ),
    )
    def perf_sockperf_latency_tcp_synthetic_busy_poll(self, result: TestResult) -> None:
        perf_sockperf(
            result,
            SOCKPERF_TCP,
            "perf_sockperf_latency_tcp_synthetic_busy_poll",
            set_busy_poll=True,
        )

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")

        # use these cleanup functions
        def do_process_cleanup(process: str) -> None:
            cleanup_process(environment, process)

        def do_sysctl_cleanup(node: Node) -> None:
            node.tools[Sysctl].reset()

        # to run parallel cleanup of processes and sysctl settings
        run_in_parallel(
            [
                partial(do_process_cleanup, x)
                for x in [
                    "lagscope",
                    "netperf",
                    "netserver",
                    "ntttcp",
                    "iperf3",
                ]
            ]
        )
        run_in_parallel(
            [partial(do_sysctl_cleanup, x) for x in environment.nodes.list()]
        )

    # Network device passthrough tests between host and guest
    @TestCaseMetadata(
        description="""
        This test case uses iperf3 to test passthrough tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=1,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_iperf_passthrough_host_guest(
        self,
        node: Node,
        result: TestResult,
    ) -> None:
        # Run iperf server on VM and client on host
        server, _ = self._configure_passthrough_nic_for_node(node)
        client = self._get_host_as_client(node)

        perf_iperf(
            test_result=result,
            connections=IPERF_TCP_CONCURRENCY,
            buffer_length_list=IPERF_TCP_BUFFER_LENGTHS,
            server=server,
            client=client,
            run_with_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses iperf3 to test passthrough udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=1,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_udp_iperf_passthrough_host_guest(
        self,
        node: Node,
        result: TestResult,
    ) -> None:
        # Run iperf server on VM and client on host with udp mode
        server, _ = self._configure_passthrough_nic_for_node(node)
        client = self._get_host_as_client(node)

        perf_iperf(
            test_result=result,
            connections=IPERF_UDP_CONCURRENCY,
            buffer_length_list=IPERF_UDP_BUFFER_LENGTHS,
            server=server,
            client=client,
            udp_mode=True,
            run_with_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sar to test passthrough network PPS (Packets Per Second)
        when running netperf with single port. Test will consider VM as
        server node and host as client node.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=1,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_single_pps_passthrough_host_guest(
        self,
        result: TestResult,
        node: Node,
    ) -> None:
        # Run netperf server on VM and client on host
        server, _ = self._configure_passthrough_nic_for_node(node)
        client = self._get_host_as_client(node)

        perf_tcp_pps(
            test_result=result,
            test_type="singlepps",
            server=server,
            client=client,
            run_with_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sar to test passthrough network PPS (Packets Per Second)
        when running netperf with multiple ports. Test will consider VM as
        server node and host as client node.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=1,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_max_pps_passthrough_host_guest(
        self,
        result: TestResult,
        node: Node,
    ) -> None:
        # Run netperf server on VM and client on host
        server, _ = self._configure_passthrough_nic_for_node(node)
        client = self._get_host_as_client(node)

        perf_tcp_pps(
            test_result=result,
            test_type="maxpps",
            server=server,
            client=client,
            run_with_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test sriov tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=1,
                memory_mb=search_space.IntRange(min=8192),
            )
        ),
    )
    def perf_tcp_ntttcp_host_guest(self, result: TestResult, node: Node) -> None:
        server, server_nic_name = self._configure_passthrough_nic_for_node(node)
        client = self._get_host_as_client(node)
        perf_ntttcp(
            test_result=result,
            client=client,
            server=server,
            server_nic_name=server_nic_name,
            client_nic_name=self._get_host_nic_name(client),
        )

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test sriov tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=1,
                memory_mb=search_space.IntRange(min=8192),
            )
        ),
    )
    def perf_udp_1k_ntttcp_host_guest(self, result: TestResult, node: Node) -> None:
        server, server_nic_name = self._configure_passthrough_nic_for_node(node)
        client = self._get_host_as_client(node)
        perf_ntttcp(
            test_result=result,
            client=client,
            server=server,
            server_nic_name=server_nic_name,
            client_nic_name=self._get_host_nic_name(client),
            udp_mode=True,
        )

    # Network device passthrough tests between 2 guests
    @TestCaseMetadata(
        description="""
        This test case uses iperf3 to test passthrough tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_iperf_passthrough_two_guest(self, result: TestResult) -> None:
        # Run iperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        client, _ = self._configure_passthrough_nic_for_node(client_node)
        server_node = cast(RemoteNode, environment.nodes[1])
        server, _ = self._configure_passthrough_nic_for_node(server_node)

        perf_iperf(
            test_result=result,
            connections=IPERF_TCP_CONCURRENCY,
            buffer_length_list=IPERF_TCP_BUFFER_LENGTHS,
            server=server,
            client=client,
            run_with_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses iperf3 to test passthrough udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_udp_iperf_passthrough_two_guest(self, result: TestResult) -> None:
        # Run iperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        client, _ = self._configure_passthrough_nic_for_node(client_node)
        server_node = cast(RemoteNode, environment.nodes[1])
        server, _ = self._configure_passthrough_nic_for_node(server_node)

        perf_iperf(
            test_result=result,
            connections=IPERF_UDP_CONCURRENCY,
            buffer_length_list=IPERF_UDP_BUFFER_LENGTHS,
            server=server,
            client=client,
            udp_mode=True,
            run_with_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sar to test passthrough network PPS (Packets Per Second)
        when running netperf with single port. Test will consider VM as
        server node and host as client node.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_single_pps_passthrough_two_guest(self, result: TestResult) -> None:
        # Run netperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        client, _ = self._configure_passthrough_nic_for_node(client_node)
        server_node = cast(RemoteNode, environment.nodes[1])
        server, _ = self._configure_passthrough_nic_for_node(server_node)

        perf_tcp_pps(
            test_result=result,
            test_type="singlepps",
            server=server,
            client=client,
            run_with_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sar to test passthrough network PPS (Packets Per Second)
        when running netperf with multiple ports. Test will consider VM as
        server node and host as client node.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_max_pps_passthrough_two_guest(self, result: TestResult) -> None:
        # Run netperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        client, _ = self._configure_passthrough_nic_for_node(client_node)
        server_node = cast(RemoteNode, environment.nodes[1])
        server, _ = self._configure_passthrough_nic_for_node(server_node)

        perf_tcp_pps(
            test_result=result,
            test_type="maxpps",
            server=server,
            client=client,
            run_with_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test sriov tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                memory_mb=search_space.IntRange(min=8192),
            )
        ),
    )
    def perf_tcp_ntttcp_two_guest(self, result: TestResult) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        client, client_nic_name = self._configure_passthrough_nic_for_node(client_node)
        print(f"client_nic_name: {client_nic_name}")
        print(f"client ip: {client.internal_address}")
        server_node = cast(RemoteNode, environment.nodes[1])
        server, server_nic_name = self._configure_passthrough_nic_for_node(server_node)
        print(f"server_nic_name: {server_nic_name}")
        print(f"server ip: {server.internal_address}")
        perf_ntttcp(
            test_result=result,
            client=client,
            server=server,
            server_nic_name=server_nic_name,
            client_nic_name=client_nic_name,
        )

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test sriov tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                memory_mb=search_space.IntRange(min=8192),
            )
        ),
    )
    def perf_udp_1k_ntttcp_two_guest(self, result: TestResult) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        client, client_nic_name = self._configure_passthrough_nic_for_node(client_node)
        print(f"client_nic_name: {client_nic_name}")
        print(f"client ip: {client.internal_address}")
        server_node = cast(RemoteNode, environment.nodes[1])
        server, server_nic_name = self._configure_passthrough_nic_for_node(server_node)
        print(f"server_nic_name: {server_nic_name}")
        print(f"server ip: {server.internal_address}")
        perf_ntttcp(
            test_result=result,
            client=client,
            server=server,
            server_nic_name=server_nic_name,
            client_nic_name=client_nic_name,
            udp_mode=True,
        )

    def _configure_passthrough_nic_for_node(
        self,
        node: RemoteNode,
    ) -> Tuple[RemoteNode, str]:
        ctx = get_node_context(node)
        if not ctx.passthrough_devices:
            raise SkippedException("No passthrough devices found for node")

        # Configure the nw interface on guest
        node.execute(
            cmd="dhclient",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="dhclient command failed",
        )

        lspci = node.tools[Lspci]
        pci_devices = lspci.get_devices_by_type(
            constants.DEVICE_TYPE_SRIOV, force_run=True
        )
        device_addr = None

        # Get the first non-virtio device
        for device in pci_devices:
            kernel_driver = lspci.get_used_module(device.slot)
            if kernel_driver != "virtio-pci":
                device_addr = device.slot
                break
        print(f"passthrough device: {device_addr}")

        # Get the interface name
        err_msg: str = "Can't find interface from PCI address"
        device_path = node.execute(
            cmd=(
                "find /sys/class/net/*/device/subsystem/devices"
                f" -name '*{device_addr}*'"
            ),
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=err_msg,
        ).stdout

        pattern = re.compile(r"/sys/class/net/(?P<INTERFACE_NAME>\w+)/device")
        interface_name_raw = find_group_in_lines(
            pattern=pattern,
            lines=device_path,
        )
        interface_name = interface_name_raw.get("INTERFACE_NAME", "")
        assert interface_name, "Can not find interface name"
        print(f"interface_name: {interface_name}")

        # Get the interface ip
        err_msg = f"Failed to get interface details for: {interface_name}"
        interface_details = node.execute(
            cmd=f"ip addr show {interface_name}",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=err_msg,
        ).stdout
        print(f"interface_details: {interface_details}")
        ip_regex = re.compile(r"\binet (?P<INTERFACE_IP>\d+\.\d+\.\d+\.\d+)/\d+\b")
        interface_ip = find_group_in_lines(
            lines=interface_details,
            pattern=ip_regex,
            single_line=False,
        )
        passthrough_nic_ip = interface_ip.get("INTERFACE_IP", "")
        print(f"passthrough_nic_ip: {passthrough_nic_ip}")
        assert passthrough_nic_ip, "Can not find interface IP"

        test_node = cast(RemoteNode, node)
        # conn_info = test_node.connection_info
        # port = conn_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT]
        # username = conn_info[constants.ENVIRONMENTS_NODES_REMOTE_USERNAME]
        # key = conn_info[constants.ENVIRONMENTS_NODES_REMOTE_PRIVATE_KEY_FILE]

        # # Set SSH connection info for the node with passthrough NIC
        # test_node.set_connection_info(
        #     address=passthrough_nic_ip,
        #     public_address=passthrough_nic_ip,
        #     public_port=port,
        #     username=username,
        #     private_key_file=key,
        # )
        test_node.internal_address = passthrough_nic_ip

        return test_node, interface_name

    def _get_host_as_client(self, node: Node) -> RemoteNode:
        ctx = get_node_context(node)
        if not ctx.passthrough_devices:
            raise SkippedException("No passthrough devices found for node")

        client = cast(RemoteNode, ctx.host_node)
        return client

    def _get_host_nic_name(self, node: RemoteNode) -> str:
        ip = node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS]

        # root [ /home/cloud ]# ip route show | grep 10.195.88.216 | grep default
        # default via 10.195.88.1 dev eth1 proto dhcp src 10.195.88.216 metric 1024
        command = f"ip route show | grep {ip} | grep default"
        route = node.execute(
            cmd=command,
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Can not get route from IP"
        ).stdout
        interface_name = route.split()[4]
        assert interface_name, "Can not find interface name"
        return interface_name
