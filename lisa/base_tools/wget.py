import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from lisa.executable import Tool
from lisa.util import LisaException, is_valid_url

if TYPE_CHECKING:
    from lisa.operating_system import Posix


class Wget(Tool):
    __pattern_path = re.compile(
        r"([\w\W]*?)(-|File) (‘|')(?P<path>.+?)(’|') (saved|already there)"
    )

    @property
    def command(self) -> str:
        return "wget"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = self.node.os  # type: ignore
        posix_os.install_packages([self])
        return self._check_exists()

    def get(
        self,
        url: str,
        file_path: str = "",
        filename: str = "",
        overwrite: bool = True,
        executable: bool = False,
        sudo: bool = False,
        force_run: bool = False,
    ) -> str:
        is_valid_url(url)

        # combine download file path
        # TODO: support current lisa folder in pathlib.
        # So that here can use the corresponding path format.
        if file_path:
            # create folder when it doesn't exist
            self.node.shell.mkdir(PurePosixPath(file_path), exist_ok=True)
            download_path = f"{file_path}/{filename}"
        else:
            download_path = f"{self.node.working_path}/{filename}"

        # remove existing file and dir to download again.
        download_pure_path = self.node.get_pure_path(download_path)
        if overwrite and self.node.shell.exists(download_pure_path):
            self.node.shell.remove(download_pure_path, recursive=True)
        command = f"'{url}' --no-check-certificate"
        if filename:
            command = f"{command} -O {download_path}"
        else:
            command = f"{command} -P {download_path}"
        command_result = self.run(
            command, no_error_log=True, shell=True, sudo=sudo, force_run=force_run
        )
        matched_result = self.__pattern_path.match(command_result.stdout)
        if matched_result:
            download_file_path = matched_result.group("path")
        else:
            raise LisaException(
                f"cannot find file path in stdout of '{command}', it may be caused "
                " due to failed download or pattern mismatch."
                f" stdout: {command_result.stdout}"
            )
        actual_file_path = self.node.execute(
            f"ls {download_file_path}", shell=True, sudo=sudo
        )
        if actual_file_path.exit_code != 0:
            raise LisaException(f"File {actual_file_path} doesn't exist.")
        if executable:
            self.node.execute(f"chmod +x {actual_file_path}", sudo=sudo)

        return actual_file_path.stdout

    def verify_internet_access(self) -> bool:
        try:
            result = self.get("https://www.azure.com", force_run=True)
            if result:
                return True
        except Exception as e:
            self._log.debug(
                f"Internet is not accessible, exception occured with wget {e}"
            )
        return False
