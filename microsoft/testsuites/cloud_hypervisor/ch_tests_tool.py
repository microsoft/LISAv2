# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
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


@dataclass
class CHPerfMetricTestResult:
    name: str = ""
    status: TestStatus = TestStatus.QUEUED
    error: str = ""
    metrics: str = ""
    trace: str = ""


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

    def run_metrics_tests(
        self,
        test_result: TestResult,
        environment: Environment,
        hypervisor: str,
        log_path: Path,
        skip: Optional[List[str]] = None,
    ) -> None:
        temp = log_path.joinpath("perf_mtr_report")
        self.per_mtr_report_file = temp.joinpath("testcase_result.json")

        perf_metrics_tests = self._list_perf_metrics_tests(hypervisor=hypervisor)
        testcases_result_list: List[CHPerfMetricTestResult] = []

        for testcase in perf_metrics_tests:
            testcase_result = CHPerfMetricTestResult()
            testcase_result.name = testcase

            try:
                result = self.run(
                    f"tests --hypervisor {hypervisor} --metrics -- -- \
                        --test-filter {testcase}",
                    timeout=self.TIME_OUT,
                    force_run=True,
                    cwd=self.repo_root,
                    no_info_log=False,  # print out result of each test
                    shell=True,
                )
                output = result.stdout.replace("\r\n", "\n")
                output = output.replace("\t", "")
                if result.exit_code != 0:
                    excep = Exception(f"Testcase failed : {testcase}", output)
                    raise excep
                metrics = self._process_perf_metric_test_result(result.stdout)
                testcase_result.status = TestStatus.PASSED
                testcase_result.metrics = metrics

            except Exception as e:
                self._log.error(f"Testcase failed , tescase name : {testcase}")
                testcase_result.status = TestStatus.FAILED
                testcase_result.error = str(e.args[0])
                testcase_result.trace = str(e.args[1])
            testcases_result_list.append(testcase_result)

        self._create_perf_metric_report(testcases_result_list)
        for testcase_result in testcases_result_list:
            msg = (
                testcase_result.metrics
                if testcase_result.status == TestStatus.PASSED
                else testcase_result.error
            )
            self._send_subtest_msg(
                test_id=test_result.id_,
                environment=environment,
                test_name=testcase_result.name,
                test_status=testcase_result.status,
                test_message=msg,
            )

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
        test_message: str = "",
    ) -> None:
        subtest_msg = create_test_result_message(
            SubTestMessage, test_id, environment, test_name, test_status, test_message
        )

        notifier.notify(subtest_msg)

    def _list_perf_metrics_tests(self, hypervisor="kvm") -> List[str]:

        self._log.debug("Listing the performance test cases")
        tests_list = []
        result = self.run(
            f"tests --hypervisor {hypervisor} --metrics -- -- --list-tests",
            timeout=self.TIME_OUT,
            force_run=True,
            cwd=self.repo_root,
            no_info_log=False,
            shell=True,
            expected_exit_code=0,
        )

        stdout = result.stdout

        # Ex. String for below regex : "boot_time_ms" (test_timeout = 2s, test_iterations = 10)
        regex = '\\"(.*)\\" \\('

        pattern = re.compile(regex)
        tests_list = pattern.findall(stdout)

        self._log.debug(f"Testcases found : {tests_list}")
        return tests_list

    def _process_perf_metric_test_result(self, output: str) -> str:
        cnt = 0
        for line in output.split("\n"):
            if line.find("git_human_readable") >= 0:
                cnt -= 1
                break
            cnt += 1

        result = "\n".join([i.strip() for i in output.split("\n")[cnt:-5]])
        self._log.debug(f"Result from testcase stdout : {result}")
        return result

    def _create_perf_metric_report(self, testcases_result_list) -> None:
        if not os.path.exists(self.per_mtr_report_file):
            os.mkdir(
                os.path.abspath(self.per_mtr_report_file).replace(
                    os.path.basename(self.per_mtr_report_file), ""
                )
            )

        testcase_result_data = {"testcases": []}
        for testcase_result in testcases_result_list:
            testcase_result_json = {
                "name": testcase_result.name,
                "status": "PASSED"
                if testcase_result.status == TestStatus.PASSED
                else "FAILED",
                "metrics": testcase_result.metrics,
                "error": testcase_result.error,
                "trace": testcase_result.trace,
            }
            testcase_result_data["testcases"].append(testcase_result_json)

        with open(self.per_mtr_report_file, "w") as f:
            f.write(json.dumps(testcase_result_data))
