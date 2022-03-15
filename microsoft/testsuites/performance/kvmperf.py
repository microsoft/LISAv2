# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import inspect
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, cast

from lisa import (
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.environment import Environment
from lisa.features import Disk
from lisa.features.network_interface import Synthetic
from lisa.messages import DiskSetupType, DiskType
from lisa.node import RemoteNode
from lisa.tools import Dnsmasq, Echo, Ip, Iptables, Lscpu, Qemu, Sysctl
from lisa.util.logger import Logger
from lisa.util.shell import ConnectionInfo, try_connect
from microsoft.testsuites.nested.common import (
    connect_nested_vm,
    parse_nested_image_variables,
)
from microsoft.testsuites.performance.common import (
    perf_disk,
    perf_ntttcp,
    reset_partitions,
    reset_raid,
    stop_raid,
)


@TestSuiteMetadata(
    area="storage",
    category="performance",
    description="""
    This test suite is to validate performance of nested VM using FIO tool.
    """,
)
class KVMPerformance(TestSuite):  # noqa
    _TIME_OUT = 12000
    _CLIENT_IMAGE = "nestedclient.qcow2"
    _SERVER_IMAGE = "nestedserver.qcow2"
    _SERVER_HOST_FWD_PORT = 60022
    _CLIENT_HOST_FWD_PORT = 60023
    _BR_NAME = "br0"
    _BR_NETWORK = "192.168.53.0"
    _BR_CIDR = "24"
    _BR_ADDR = "192.168.53.1"
    _BR_DHCP_RANGE = "192.168.53.2,192.168.53.254"
    _SERVER_IP_ADDR = "192.168.53.14"
    _CLIENT_IP_ADDR = "192.168.53.15"
    _SERVER_TAP = "tap0"
    _CLIENT_TAP = "tap1"
    _NIC_NAME = "ens4"

    @TestCaseMetadata(
        description="""
        This test case is to validate performance of nested VM using fio tool
        with single l1 data disk attached to the l2 VM.
        """,
        priority=3,
        timeout=_TIME_OUT,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=1),
            ),
        ),
    )
    def perf_nested_kvm_storage_singledisk(
        self, node: RemoteNode, environment: Environment, variables: Dict[str, Any]
    ) -> None:
        self._storage_perf_qemu(node, environment, variables, setup_raid=False)

    @TestCaseMetadata(
        description="""
        This test case is to validate performance of nested VM using fio tool with raid0
        configuratrion of 6 l1 data disk attached to the l2 VM.
        """,
        priority=3,
        timeout=_TIME_OUT,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.PremiumSSDLRS,
                data_disk_iops=search_space.IntRange(min=5000),
                data_disk_count=search_space.IntRange(min=6),
            ),
        ),
    )
    def perf_nested_kvm_storage_multidisk(
        self, node: RemoteNode, environment: Environment, variables: Dict[str, Any]
    ) -> None:
        self._storage_perf_qemu(node, environment, variables)

    @TestCaseMetadata(
        description="""
        This test case runs ntttcp test on two nested VMs on same L1 guest
        connected with private bridge
        """,
        priority=3,
        timeout=_TIME_OUT,
    )
    def perf_nested_kvm_ntttcp_private_bridge(
        self,
        node: RemoteNode,
        environment: Environment,
        variables: Dict[str, Any],
        log: Logger,
    ) -> None:
        (
            nested_image_username,
            nested_image_password,
            _,
            nested_image_url,
        ) = parse_nested_image_variables(variables)

        try:
            # setup bridge and taps
            node.tools[Ip].setup_bridge(self._BR_NAME, self._BR_ADDR)
            node.tools[Ip].setup_tap(self._CLIENT_TAP, self._BR_NAME)
            node.tools[Ip].setup_tap(self._SERVER_TAP, self._BR_NAME)

            # setup server and client
            server = connect_nested_vm(
                node,
                nested_image_username,
                nested_image_password,
                self._SERVER_HOST_FWD_PORT,
                nested_image_url,
                image_name=self._SERVER_IMAGE,
                nic_model="virtio-net-pci",
                taps=[self._SERVER_TAP],
                name="server",
                log=log,
            )
            server.tools[Ip].add_ipv4_address(
                self._NIC_NAME, f"{self._SERVER_IP_ADDR}/24"
            )
            server.tools[Ip].up(self._NIC_NAME)
            server.internal_address = self._SERVER_IP_ADDR
            server.nics.default_nic = self._NIC_NAME
            server.capability.network_interface = Synthetic()

            client = connect_nested_vm(
                node,
                nested_image_username,
                nested_image_password,
                self._CLIENT_HOST_FWD_PORT,
                nested_image_url,
                image_name=self._CLIENT_IMAGE,
                nic_model="virtio-net-pci",
                taps=[self._CLIENT_TAP],
                name="client",
                stop_existing_vm=False,
                log=log,
            )
            client.tools[Ip].add_ipv4_address(
                self._NIC_NAME, f"{self._CLIENT_IP_ADDR}/24"
            )
            client.tools[Ip].up(self._NIC_NAME)
            client.nics.default_nic = self._NIC_NAME
            client.capability.network_interface = Synthetic()

            # run ntttcp test
            perf_ntttcp(
                environment, server, client, test_case_name=inspect.stack()[1][3]
            )
        finally:
            # clear bridge and taps
            node.tools[Ip].delete_interface(self._BR_NAME)
            node.tools[Ip].delete_interface(self._SERVER_TAP)
            node.tools[Ip].delete_interface(self._CLIENT_TAP)

            # stop running QEMU instances
            node.tools[Qemu].stop_vm()

    @TestCaseMetadata(
        description="""
        This script runs ntttcp test on two nested VMs on different L1 guests
        connected with NAT
        """,
        priority=3,
        timeout=_TIME_OUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=schema.NetworkInterfaceOptionSettings(
                nic_count=search_space.IntRange(min=2),
            ),
        ),
    )
    def perf_nested_kvm_ntttcp_different_l1_nat(
        self, environment: Environment, variables: Dict[str, Any], log_path: Path
    ) -> None:
        server_l1 = cast(RemoteNode, environment.nodes[0])
        client_l1 = cast(RemoteNode, environment.nodes[1])

        # parse nested image variables
        (
            nested_image_username,
            nested_image_password,
            _,
            nested_image_url,
        ) = parse_nested_image_variables(variables)

        try:

            # setup nat on client and server
            self._setup_nat(
                server_l1,
                self._BR_NAME,
                self._BR_NETWORK,
                self._BR_CIDR,
                self._BR_ADDR,
                f"{self._SERVER_IP_ADDR},{self._SERVER_IP_ADDR}",
                self._SERVER_TAP,
            )
            self._setup_nat(
                client_l1,
                self._BR_NAME,
                self._BR_NETWORK,
                self._BR_CIDR,
                self._BR_ADDR,
                f"{self._CLIENT_IP_ADDR},{self._CLIENT_IP_ADDR}",
                self._CLIENT_TAP,
            )

            # setup l2 vm on server and client
            server_l2 = connect_nested_vm(
                server_l1,
                nested_image_username,
                nested_image_password,
                self._SERVER_HOST_FWD_PORT,
                nested_image_url,
                image_name=self._SERVER_IMAGE,
                taps=[self._SERVER_TAP],
                stop_existing_vm=True,
                name="server",
            )
            server_l2.internal_address = server_l1.nics.get_nic("eth1").ip_addr
            server_l2.nics.default_nic = self._NIC_NAME
            server_l2.capability.network_interface = Synthetic()
            self._configure_ssh(
                server_l1,
                server_l2,
                self._SERVER_HOST_FWD_PORT,
                self._SERVER_IP_ADDR,
                nested_image_username,
                nested_image_password,
            )

            # setup l2 vm on client
            client_l2 = connect_nested_vm(
                client_l1,
                nested_image_username,
                nested_image_password,
                self._CLIENT_HOST_FWD_PORT,
                nested_image_url,
                image_name=self._CLIENT_IMAGE,
                taps=[self._CLIENT_TAP],
                stop_existing_vm=True,
                name="client",
            )
            client_l2.internal_address = client_l1.nics.get_nic("eth1").ip_addr
            client_l2.nics.default_nic = self._NIC_NAME
            client_l2.capability.network_interface = Synthetic()
            self._configure_ssh(
                client_l1,
                client_l2,
                self._CLIENT_HOST_FWD_PORT,
                self._CLIENT_IP_ADDR,
                nested_image_username,
                nested_image_password,
            )
        finally:
            # stop running QEMU instances
            server_l1.tools[Qemu].stop_vm()
            client_l1.tools[Qemu].stop_vm()

            # clear bridge and taps
            server_l1.tools[Ip].delete_interface(self._BR_NAME)
            client_l1.tools[Ip].delete_interface(self._BR_NAME)

            # flush ip tables
            server_l1.tools[Iptables].reset_table()
            server_l1.tools[Iptables].reset_table("nat")
            client_l1.tools[Iptables].reset_table()
            client_l1.tools[Iptables].reset_table("nat")

        # # run ntttcp test
        perf_ntttcp(
            environment, server_l2, client_l2, test_case_name=inspect.stack()[1][3]
        )

    def _setup_nat(
        self,
        node: RemoteNode,
        bridge_name: str,
        bridge_network: str,
        bridge_cidr: str,
        bridge_addr: str,
        bridge_dhcp_range: str,
        tap_name: str,
    ) -> None:
        # enable ip forwarding
        node.tools[Sysctl].write("net.ipv4.ip_forward", "1")

        # setup bridge
        node.tools[Ip].setup_bridge(bridge_name, f"{bridge_addr}/{bridge_cidr}")
        node.tools[Ip].set_bridge_configuration(bridge_name, "stp_state", "0")
        node.tools[Ip].set_bridge_configuration(bridge_name, "forward_delay", "0")

        # setup tap
        node.tools[Ip].setup_tap(tap_name, bridge_name)

        # setup filter table
        node.tools[Iptables].reset_table()
        node.tools[Iptables].accept(bridge_name, 67)
        node.tools[Iptables].accept(bridge_name, 67, "udp")
        node.tools[Iptables].accept(bridge_name, 53)
        node.tools[Iptables].accept(bridge_name, 53, "udp")
        node.tools[Iptables].run(
            f"-A FORWARD -i {bridge_name} -o {bridge_name} -j ACCEPT",
            sudo=True,
            force_run=True,
        )
        node.tools[Iptables].run(
            f"-A FORWARD -s {bridge_network}/{bridge_cidr} -i {bridge_name} -j ACCEPT",
            sudo=True,
            force_run=True,
        )
        node.tools[Iptables].run(
            (
                f"-A FORWARD -d {bridge_network}/{bridge_cidr} -o {bridge_name} "
                "-m state --state NEW,RELATED,ESTABLISHED -j ACCEPT"
            ),
            sudo=True,
            force_run=True,
        )
        node.tools[Iptables].run(
            (
                f"-A FORWARD -o {bridge_name} -j REJECT "
                "--reject-with icmp-port-unreachable"
            ),
            sudo=True,
            force_run=True,
        )
        node.tools[Iptables].run(
            (
                f"-A FORWARD -i {bridge_name} -j REJECT "
                "--reject-with icmp-port-unreachable"
            ),
            sudo=True,
            force_run=True,
        )

        # setup nat forwarding
        node.tools[Iptables].reset_table("nat")
        node.tools[Iptables].run(
            f"-t nat -A POSTROUTING -s {bridge_network}/{bridge_cidr} -j MASQUERADE",
            sudo=True,
            force_run=True,
        )

        # reset lease file
        node.execute(
            f"cp /dev/null /var/run/qemu-dnsmasq-{bridge_name}.leases", sudo=True
        )

        # start dnsmasq
        node.tools[Dnsmasq].start(bridge_name, bridge_addr, bridge_dhcp_range)

    def _configure_ssh(
        self,
        node_l1: RemoteNode,
        node_l2: RemoteNode,
        host_fwd_port: int,
        l2_ip_addr: str,
        nested_image_username: str,
        nested_image_password: str,
    ) -> None:
        # configure rc.local to run dhclient on reboot
        node_l2.tools[Echo].write_to_file(
            "#!/bin/sh -e", PurePosixPath("/etc/rc.local"), append=True, sudo=True
        )
        node_l2.tools[Echo].write_to_file(
            "ip link set dev ens4 up",
            PurePosixPath("/etc/rc.local"),
            append=True,
            sudo=True,
        )
        node_l2.tools[Echo].write_to_file(
            "dhclient ens4", PurePosixPath("/etc/rc.local"), append=True, sudo=True
        )
        node_l2.execute("chmod +x /etc/rc.local", sudo=True)

        # reboot l2 vm
        node_l2.execute_async("reboot", sudo=True)

        # route traffic on `eth0` port`host_fwd_port` on l1 vm to l2 vm
        node_l1.tools[Iptables].run(
            (
                f"-t nat -A PREROUTING -i eth0 -p tcp --dport {host_fwd_port} "
                f"-j DNAT --to {l2_ip_addr}:22"
            ),
            sudo=True,
            force_run=True,
        )

        # route all tcp traffic on `eth1` port on l1 vm to l2 vm
        node_l1.tools[Iptables].run(
            (
                f"-t nat -A PREROUTING -i eth1 -d {node_l2.internal_address} "
                f"-p tcp -j DNAT --to {l2_ip_addr}"
            ),
            sudo=True,
            force_run=True,
        )

        # wait till l2 vm is up
        try_connect(
            ConnectionInfo(
                address=node_l1.public_address,
                port=host_fwd_port,
                username=nested_image_username,
                password=nested_image_password,
            )
        )

    def _storage_perf_qemu(
        self,
        node: RemoteNode,
        environment: Environment,
        variables: Dict[str, Any],
        filename: str = "/dev/sdb",
        start_iodepth: int = 1,
        max_iodepth: int = 1024,
        setup_raid: bool = True,
    ) -> None:
        (
            nested_image_username,
            nested_image_password,
            nested_image_port,
            nested_image_url,
        ) = parse_nested_image_variables(variables)

        l1_data_disks = node.features[Disk].get_raw_data_disks()
        l1_data_disk_count = len(l1_data_disks)

        # setup raid on l1 data disks
        if setup_raid:
            disks = ["md0"]
            l1_partition_disks = reset_partitions(node, l1_data_disks)
            stop_raid(node)
            reset_raid(node, l1_partition_disks)
        else:
            disks = ["sdb"]

        # get l2 vm
        l2_vm = connect_nested_vm(
            node,
            nested_image_username,
            nested_image_password,
            nested_image_port,
            nested_image_url,
            disks=disks,
        )

        # Qemu command exits immediately but the VM requires some time to boot up.
        time.sleep(60)
        l2_vm.tools[Lscpu].get_core_count()

        # Each fio process start jobs equal to the iodepth to read/write from
        # the disks. The max number of jobs can be equal to the core count of
        # the node.
        # Examples:
        # iodepth = 4, core count = 8 => max_jobs = 4
        # iodepth = 16, core count = 8 => max_jobs = 8
        num_jobs = []
        iodepth_iter = start_iodepth
        core_count = node.tools[Lscpu].get_core_count()
        while iodepth_iter <= max_iodepth:
            num_jobs.append(min(iodepth_iter, core_count))
            iodepth_iter = iodepth_iter * 2

        # run fio test
        perf_disk(
            l2_vm,
            start_iodepth,
            max_iodepth,
            filename,
            test_name=inspect.stack()[1][3],
            core_count=core_count,
            disk_count=l1_data_disk_count,
            disk_setup_type=DiskSetupType.raid0,
            disk_type=DiskType.premiumssd,
            environment=environment,
            num_jobs=num_jobs,
            size_gb=8,
            overwrite=True,
        )
