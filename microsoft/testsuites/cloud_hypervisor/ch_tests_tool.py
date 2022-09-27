# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, List, Optional, Type

from assertpy.assertpy import assert_that

from lisa import Environment, notifier
from lisa.executable import Tool
from lisa.messages import SubTestMessage, TestStatus, create_test_result_message
from lisa.operating_system import CBLMariner
from lisa.testsuite import TestResult
from lisa.tools import Docker, Echo, Git, Whoami


@dataclass
class CloudHypervisorTestResult:
    name: str = ""
    status: TestStatus = TestStatus.QUEUED


class CloudHypervisorTests(Tool):
    TIME_OUT = 7200

    repo = "https://github.com/cloud-hypervisor/cloud-hypervisor.git"

    cmd_path: PurePath
    repo_root: PurePath

    @property
    def command(self) -> str:
        return str(self.cmd_path)

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Docker]

    def run_tests(
        self,
        test_result: TestResult,
        environment: Environment,
        test_type: str,
        hypervisor: str,
        skip: Optional[List[str]] = None,
    ) -> None:
        if skip is not None:
            skip_args = " ".join(map(lambda t: f"--skip {t}", skip))
        else:
            skip_args = ""

        result = self.run(
            f"tests --hypervisor {hypervisor} --{test_type} -- -- {skip_args}"
            " -Z unstable-options --format json",
            timeout=self.TIME_OUT,
            force_run=True,
            cwd=self.repo_root,
            no_info_log=False,  # print out result of each test
            shell=True,
        )

        results = self._extract_test_results(result.stdout)
        failures = [r.name for r in results if r.status == TestStatus.FAILED]
        if not failures:
            result.assert_exit_code()

        for r in results:
            self._send_subtest_msg(
                test_result.id_,
                environment,
                r.name,
                r.status,
            )

        assert_that(failures, f"Unexpected failures: {failures}").is_empty()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        tool_path = self.get_tool_path(use_global=True)
        self.repo_root = tool_path / "cloud-hypervisor"
        self.cmd_path = self.repo_root / "scripts" / "dev_cli.sh"

    def _install(self) -> bool:
        git = self.node.tools[Git]
        git.clone(self.repo, self.get_tool_path(use_global=True))
        if isinstance(self.node.os, CBLMariner):
            daemon_json_file = PurePath("/etc/docker/daemon.json")
            daemon_json = '{"default-ulimits":{"nofile":{"Hard":65535,"Name":"nofile","Soft":65535}}}'  # noqa: E501
            self.node.tools[Echo].write_to_file(
                daemon_json, daemon_json_file, sudo=True
            )

        self.node.execute("groupadd -f docker", expected_exit_code=0)
        username = self.node.tools[Whoami].get_username()
        res = self.node.execute("getent group docker", expected_exit_code=0)
        if username not in res.stdout:  # if current user is not in docker group
            self.node.execute(f"usermod -a -G docker {username}", sudo=True)
            # reboot for group membership change to take effect
            self.node.reboot()

        self.node.tools[Docker].start()

        return self._check_exists()

    def _extract_test_results(self, output: str) -> List[CloudHypervisorTestResult]:
        results: List[CloudHypervisorTestResult] = []

        # Cargo will output test status for each test separately in JSON format. Parse
        # the output line by line to obtain the list of all tests run along with their
        # outcomes.
        #
        # Example output:
        # { "type": "test", "event": "ok", "name": "integration::test_vfio" }
        lines = output.split("\n")
        for line in lines:
            result = {}
            try:
                result = json.loads(line)
            except json.decoder.JSONDecodeError:
                continue

            if type(result) is not dict:
                continue

            if "type" not in result or result["type"] != "test":
                continue

            if "event" not in result or result["event"] not in ["ok", "failed"]:
                continue

            status = TestStatus.PASSED if result["event"] == "ok" else TestStatus.FAILED
            results.append(
                CloudHypervisorTestResult(
                    name=result["name"],
                    status=status,
                )
            )

        return results

    def _send_subtest_msg(
        self,
        test_id: str,
        environment: Environment,
        test_name: str,
        test_status: TestStatus,
    ) -> None:
        subtest_msg = create_test_result_message(
            SubTestMessage,
            test_id,
            environment,
            test_name,
            test_status,
        )

        notifier.notify(subtest_msg)
