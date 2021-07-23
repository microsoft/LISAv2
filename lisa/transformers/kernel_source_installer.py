# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, List, Optional, Type, cast

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.node import Node
from lisa.operating_system import Redhat, Ubuntu
from lisa.tools import Echo, Git, Make, Uname
from lisa.util import LisaException, subclasses
from lisa.util.logger import Logger, get_logger

from .kernel_installer import BaseInstaller, BaseInstallerSchema


@dataclass_json()
@dataclass
class BaseModifierSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    ...


@dataclass_json()
@dataclass
class BaseLocationSchema(schema.TypedSchema, schema.ExtendableSchemaMixin):
    ...


@dataclass_json()
@dataclass
class LocalLocationSchema(BaseLocationSchema):
    path: str = field(
        default="",
        metadata=schema.metadata(
            required=True,
        ),
    )


@dataclass_json()
@dataclass
class RepoLocationSchema(LocalLocationSchema):
    # source code repo
    repo: str = "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git"
    ref: str = ""

    # fail the run if code exists
    fail_on_code_exists: bool = False
    cleanup_code: bool = False


@dataclass_json()
@dataclass
class SourceInstallerSchema(BaseInstallerSchema):
    location: Optional[BaseLocationSchema] = field(
        default=None, metadata=schema.metadata(required=True)
    )



class SourceInstaller(BaseInstaller):
    @classmethod
    def type_name(cls) -> str:
        return "source"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return SourceInstallerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def validate(self) -> None:
        # nothing to validate before source installer started.
        ...

    def install(self) -> str:
        node = self._node
        runbook: SourceInstallerSchema = self.runbook
        assert runbook.location, "the repo must be defined."

        self._install_build_tools(node)

        factory = subclasses.Factory[BaseLocation](BaseLocation)
        source = factory.create_by_runbook(
            runbook=runbook.location, node=node, parent_log=self._log
        )

        code_path = source.get_source_code()
        assert node.shell.exists(code_path), f"cannot find code path: {code_path}"
        self._log.info(f"kernel code path: {code_path}")

        self._build_code(node=node, code_path=code_path)

        self._install_build(node=node, code_path=code_path)

        result = node.execute("make kernelrelease", cwd=code_path)
        kernel_version = result.stdout
        result.assert_exit_code(0, f"failed on get kernel version: {kernel_version}")

        # copy current config back to system folder.
        result = node.execute(
            f"cp .config /boot/config-{kernel_version}", cwd=code_path, sudo=True
        )
        result.assert_exit_code()

        return kernel_version

    def _install_build(self, node: Node, code_path: PurePath) -> None:
        make = node.tools[Make]
        make.make(arguments="modules", cwd=code_path, sudo=True)

        make.make(arguments="modules_install", cwd=code_path, sudo=True)

        make.make(arguments="install", cwd=code_path, sudo=True)

        # The build for Redhat needs extra steps than RPM package. So put it
        # here, not in OS.
        if isinstance(node.os, Redhat):
            result = node.execute("grub2-set-default 0", sudo=True)
            result.assert_exit_code()

            result = node.execute("grub2-mkconfig -o /boot/grub2/grub.cfg", sudo=True)
            result.assert_exit_code()

    def _build_code(self, node: Node, code_path: PurePath) -> None:
        self._log.info("building code...")

        uname = node.tools[Uname]
        kernel_information = uname.get_linux_information()

        result = node.execute(
            f"cp /boot/config-{kernel_information.kernel_version} .config",
            cwd=code_path,
        )
        result.assert_exit_code()

        # workaround failures.
        #
        # make[1]: *** No rule to make target 'debian/canonical-certs.pem',
        # needed by 'certs/x509_certificate_list'.  Stop.
        #
        # make[1]: *** No rule to make target 'certs/rhel.pem', needed by
        # 'certs/x509_certificate_list'.  Stop.
        result = node.execute(
            "scripts/config --disable SYSTEM_TRUSTED_KEYS",
            cwd=code_path,
            shell=True,
        )
        result.assert_exit_code()

        # the gcc version of Redhat 7.x is too old. Upgrade it.
        if isinstance(node.os, Redhat) and node.os.release_version < "8.0.0":
            node.os.install_packages(["devtoolset-8"])
            result = node.execute("mv /bin/gcc /bin/gcc_back", sudo=True)
            result.assert_exit_code()
            result = node.execute(
                "ln -s /opt/rh/devtoolset-8/root/usr/bin/gcc /bin/gcc", sudo=True
            )
            result.assert_exit_code()

        make = node.tools[Make]
        make.make(arguments="olddefconfig", cwd=code_path)

        # set timeout to 2 hours
        make.make(arguments="", cwd=code_path, timeout=60 * 60 * 2)

    def _install_build_tools(self, node: Node) -> None:
        os = node.os
        self._log.info("installing build tools")
        if isinstance(os, Redhat):
            os.install_packages(["elfutils-libelf-devel", "openssl-devel", "dwarves"])

            result = node.execute('yum -y groupinstall "Development Tools"', sudo=True)
            result.assert_exit_code()

            if os.release_version < "8.0.0":
                # git from default CentOS/RedHat 7.x does not support git tag format
                # syntax temporarily use a community repo, then remove it
                node.execute("yum remove -y git", sudo=True)
                node.execute(
                    "rpm -U https://centos7.iuscommunity.org/ius-release.rpm", sudo=True
                )
                os.install_packages("git2u")
                node.execute("rpm -e ius-release", sudo=True)
        elif isinstance(os, Ubuntu):
            # ccache is used to speed up recompilation
            # node.execute("command -v ccache", shell=True)
            # node.execute("export PATH=/usr/lib/ccache:$PATH", shell=True)
            os.install_packages(
                [
                    "git",
                    "build-essential",
                    "bison",
                    "flex",
                    "libelf-dev",
                    "libncurses5-dev",
                    "xz-utils",
                    "libssl-dev",
                    "bc",
                    "ccache",
                ]
            )
        else:
            raise LisaException(
                f"os '{os.name}' doesn't support in {self.type_name()}. "
                f"Implement its build dependencies installation there."
            )


class BaseLocation(subclasses.BaseClassWithRunbookMixin):
    def __init__(
        self,
        runbook: Any,
        node: Node,
        parent_log: Logger,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook, *args, **kwargs)
        self._node = node
        self._log = get_logger("kernel_builder", parent=parent_log)

    def get_source_code(self) -> PurePath:
        raise NotImplementedError()


class RepoLocation(BaseLocation):
    @classmethod
    def type_name(cls) -> str:
        return "repo"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return RepoLocationSchema

    def get_source_code(self) -> PurePath:
        runbook = cast(RepoLocationSchema, self.runbook)
        code_path = _get_code_path(runbook.path, self._node, f"{self.type_name()}_code")

        # expand env variables
        echo = self._node.tools[Echo]
        echo_result = echo.run(str(code_path), shell=True)

        code_path = self._node.get_pure_path(echo_result.stdout)

        if runbook.cleanup_code and self._node.shell.exists(code_path):
            self._node.shell.remove(code_path, True)

        # create and give permission on code folder
        self._node.execute(f"mkdir -p {code_path}", sudo=True)
        self._node.execute(f"chmod -R 777 {code_path}", sudo=True)

        self._log.info(f"cloning code from {runbook.repo} to {code_path}...")
        git = self._node.tools[Git]
        code_path = git.clone(
            url=runbook.repo, cwd=code_path, fail_on_exists=runbook.fail_on_code_exists
        )

        git.fetch(cwd=code_path)

        if runbook.ref:
            self._log.info(f"checkout code from: '{runbook.ref}'")
            git.checkout(ref=runbook.ref, cwd=code_path)

        return code_path


class LocalLocation(BaseLocation):
    @classmethod
    def type_name(cls) -> str:
        return "local"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return LocalLocationSchema

    def get_source_code(self) -> PurePath:
        runbook: LocalLocationSchema = self.runbook
        return self._node.get_pure_path(runbook.path)


def _get_code_path(path: str, node: Node, default_name: str) -> PurePath:
    if path:
        code_path = node.get_pure_path(path)
    else:
        code_path = node.working_path / default_name

    return code_path
