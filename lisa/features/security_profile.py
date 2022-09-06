# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from typing import Any, List, Type, Union

from dataclasses_json import dataclass_json

from lisa import schema, search_space
from lisa.feature import Feature
from lisa.util import constants, field_metadata

FEATURE_NAME_SECURITY_PROFILE = "Security_Profile"


class SecurityProfileType(str, Enum):
    Standard = constants.SECURITY_PROFILE_NONE
    CVM = constants.SECURITY_PROFILE_CVM
    Boot = constants.SECURITY_PROFILE_BOOT


security_profile_priority: List[SecurityProfileType] = [
    SecurityProfileType.Standard,
    SecurityProfileType.Boot,
    SecurityProfileType.CVM,
]


@dataclass_json()
@dataclass()
class SecurityProfileSettings(schema.FeatureSettings):
    type: str = FEATURE_NAME_SECURITY_PROFILE
    security_profile: Union[
        search_space.SetSpace[SecurityProfileType], SecurityProfileType
    ] = field(  # type:ignore
        default_factory=partial(
            search_space.SetSpace,
            items=[
                SecurityProfileType.Standard,
                SecurityProfileType.Boot,
                SecurityProfileType.CVM,
            ],
        ),
        metadata=field_metadata(
            decoder=partial(
                search_space.decode_set_space_by_type, base_type=SecurityProfileType
            )
        ),
    )

    def __hash__(self) -> int:
        return hash(self._get_key())

    def _get_key(self) -> str:
        return f"{self.type}/{self.security_profile}"

    def _call_requirement_method(self, method_name: str, capability: Any) -> Any:
        value = SecurityProfileSettings()
        value.security_profile = getattr(
            search_space, f"{method_name}_setspace_by_priority"
        )(
            self.security_profile,
            capability.security_profile,
            security_profile_priority,
        )
        return value

    def check(self, capability: Any) -> search_space.ResultReason:
        assert isinstance(
            capability, SecurityProfileSettings
        ), f"actual: {type(capability)}"
        result = super().check(capability)
        result.merge(
            search_space.check_setspace(
                self.security_profile, capability.security_profile
            ),
            "security_profile",
        )
        return result


class SecurityProfile(Feature):
    @classmethod
    def on_before_deployment(cls, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError()

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_SECURITY_PROFILE

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return SecurityProfileSettings

    @classmethod
    def can_disable(cls) -> bool:
        return True

    @classmethod
    def _enable_secure_boot(cls, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError()

    def enabled(self) -> bool:
        return True


SecureBootEnabled = partial(
    SecurityProfileSettings,
    security_profile=search_space.SetSpace(
        True, [SecurityProfileType.Boot, SecurityProfileType.CVM]
    ),
)

CvmEnabled = partial(
    SecurityProfileSettings,
    security_profile=search_space.SetSpace(True, [SecurityProfileType.CVM]),
)
