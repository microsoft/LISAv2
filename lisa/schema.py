# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, Union, cast

from dataclasses_json import (
    CatchAll,
    DataClassJsonMixin,
    Undefined,
    config,
    dataclass_json,
)
from marshmallow import ValidationError, fields, validate

from lisa import search_space
from lisa.secret import PATTERN_HEADTAIL, add_secret
from lisa.util import BaseClassMixin, LisaException, constants

"""
Schema is dealt with three components,
1. dataclasses. It's a builtin class, uses to define schema of an instance. field()
   function uses to describe a field.
2. dataclasses_json. Serializer. config() function customizes this component.
3. marshmallow. Validator. It's wrapped by dataclasses_json. config(mm_field=xxx)
   function customizes this component.
"""


T = TypeVar("T")


def metadata(
    field_function: Optional[Callable[..., Any]] = None, *args: Any, **kwargs: Any
) -> Any:
    """
    wrap for shorter
    """
    if field_function is None:
        field_function = fields.Raw
    assert field_function
    encoder = kwargs.pop("encoder", None)
    decoder = kwargs.pop("decoder", None)
    # keep data_key for underlying marshmallow
    field_name = kwargs.get("data_key")
    return config(
        field_name=cast(str, field_name),
        encoder=encoder,
        decoder=decoder,
        mm_field=field_function(*args, **kwargs),
    )


class ListableValidator(validate.Validator):
    default_message = ""

    def __init__(
        self,
        value_type: type,
        value_validator: Optional[
            Union[validate.Validator, List[validate.Validator]]
        ] = None,
        error: str = "",
    ) -> None:
        self._value_type: Any = value_type
        if value_validator is None:
            self._inner_validator: List[validate.Validator] = []
        elif callable(value_validator):
            self._inner_validator = [value_validator]
        elif isinstance(value_validator, list):
            self._inner_validator = list(value_validator)
        else:
            raise ValueError(
                "The 'value_validator' parameter must be a callable "
                "or a collection of callables."
            )
        self.error: str = error or self.default_message

    def _repr_args(self) -> str:
        return f"_inner_validator={self._inner_validator}"

    def _format_error(self, value: Any) -> str:
        return self.error.format(input=value)

    def __call__(self, value: Any) -> Any:
        if isinstance(value, self._value_type):
            if self._inner_validator:
                for validator in self._inner_validator:
                    validator(value)
        elif isinstance(value, list):
            for value_item in value:
                assert isinstance(value_item, self._value_type), (
                    f"must be '{self._value_type}' but '{value_item}' "
                    f"is '{type(value_item)}'"
                )
                if self._inner_validator:
                    for validator in self._inner_validator:
                        validator(value_item)
        elif value is not None:
            raise ValidationError(
                f"must be Union[{self._value_type}, List[{self._value_type}]], "
                f"but '{value}' is '{type(value)}'"
            )
        return value


@dataclass_json(undefined=Undefined.INCLUDE)
@dataclass
class ExtendableSchemaMixin:
    extended_schemas: CatchAll = field(default_factory=dict)  # type: ignore

    def get_extended_runbook(self, runbook_type: Type[T], type_name: str = "") -> T:
        """
        runbook_type: type of runbook
        field_name: the field name which stores the data, if it's "", get it from type
        """
        if not hasattr(self, "_extended_runbook"):
            type_name = self.__resolve_type_name(
                runbook_type=runbook_type, type_name=type_name
            )
            if self.extended_schemas and type_name in self.extended_schemas:
                self._extended_runbook: T = load_by_type(
                    runbook_type, self.extended_schemas[type_name]
                )
            else:
                # value may be filled outside, so hold and return an object.
                self._extended_runbook = runbook_type()

            # if there is any extra key, raise exception to help user find it earlier.
            if self.extended_schemas and len(self.extended_schemas) > 0:
                expected_extra_count = 0
                if type_name in self.extended_schemas:
                    expected_extra_count = 1
                if len(self.extended_schemas) > expected_extra_count:
                    extra_names = [
                        name for name in self.extended_schemas if name != type_name
                    ]
                    raise LisaException(
                        f"unknown keys in extendable schema [{runbook_type.__name__}]: "
                        f"{extra_names}"
                    )

        return self._extended_runbook

    def set_extended_runbook(self, runbook: Any, type_name: str = "") -> None:
        self._extended_runbook = runbook
        if self.extended_schemas and type_name in self.extended_schemas:
            # save extended runbook back to raw dict
            self.extended_schemas[type_name] = runbook.to_dict()

    def __resolve_type_name(self, runbook_type: Type[Any], type_name: str) -> str:
        assert issubclass(
            runbook_type, DataClassJsonMixin
        ), "runbook_type must annotate from DataClassJsonMixin"
        if not type_name:
            assert hasattr(self, constants.TYPE), (
                f"cannot find type attr on '{runbook_type.__name__}'."
                f"either set field_name or make sure type attr exists."
            )
            type_name = getattr(self, constants.TYPE)
        return type_name

    def __repr__(self) -> str:
        result = ""
        if hasattr(self, "_extended_runbook"):
            result = f"ext:{self._extended_runbook}"
        elif self.extended_schemas:
            result = f"ext:{self.extended_schemas}"
        return result


@dataclass_json()
@dataclass
class TypedSchema:
    type: str = field(default="", metadata=metadata(required=True))


@dataclass_json()
@dataclass
class Transformer(TypedSchema, ExtendableSchemaMixin):
    # the name can be referenced by other transformers. If it's not specified,
    # the type will be used.
    name: str = ""
    # prefix of generated variables. if it's not specified, the name will be
    # used. For example, a variable called "a" with the prefix "b", so the
    # variable name will be "b_a" in the variable dict
    prefix: str = ""

    # specify which transformers are depended.
    depends_on: List[str] = field(default_factory=list)
    # rename some of variables for easier use.
    rename: Dict[str, str] = field(default_factory=dict)
    # enable this transformer or not, only enabled transformers run actually.
    enabled: bool = True

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if not self.name:
            self.name = self.type
        if not self.prefix:
            self.prefix = self.name


@dataclass_json()
@dataclass
class Combinator(TypedSchema, ExtendableSchemaMixin):
    type: str = field(
        default=constants.COMBINATOR_GRID, metadata=metadata(required=True)
    )


@dataclass_json()
@dataclass
class Strategy:
    """
    node_path is the path of yaml node. For example:
        environment.nodes
    if node_path doesn't present, it means to all.

    operations include:
    overwrite: default behavior. add non-exist items and replace exist.
    remove: remove specified path totally.
    add: add non-exist, not replace exist.
    """

    node_path: str = field(default="", metadata=metadata(required=True))
    operation: str = field(
        default=constants.OPERATION_OVERWRITE,
        metadata=metadata(
            required=True,
            validate=validate.OneOf(
                [
                    constants.OPERATION_ADD,
                    constants.OPERATION_OVERWRITE,
                    constants.OPERATION_REMOVE,
                ]
            ),
        ),
    )


@dataclass_json()
@dataclass
class Include:
    """
    Inclusion of runbook logic, for similar runs.
    """

    path: str = field(default="", metadata=metadata(required=True))
    strategy: Union[List[Strategy], Strategy, None] = None


@dataclass_json()
@dataclass
class Extension:
    path: str
    name: Optional[str] = None

    @classmethod
    def from_raw(cls, raw_data: Any) -> List["Extension"]:
        results: List[Extension] = []

        assert isinstance(raw_data, list), f"actual: {type(raw_data)}"
        for extension in raw_data:
            # convert to structured Extension
            if isinstance(extension, str):
                extension = Extension(path=extension)
            elif isinstance(extension, dict):
                extension = load_by_type(Extension, extension)
            results.append(extension)

        return results


@dataclass_json()
@dataclass
class VariableEntry:
    value: Union[str, bool, int] = ""
    is_secret: bool = False
    # True means this variable can be used in test cases.
    is_case_visible: bool = False
    mask: str = ""


@dataclass_json()
@dataclass
class Variable:
    """
    it uses to support variables in other fields.
    duplicate items will be overwritten one by one.
    if a variable is not defined here, LISA can fail earlier to ask check it.
    file path is relative to LISA command starts.
    """

    # If it's secret, it will be removed from log and other output information.
    # secret files also need to be removed after test
    # it's not recommended highly to put secret in runbook directly.
    is_secret: bool = False

    # continue to support v2 format. it's simple.
    file: str = field(
        default="",
        metadata=metadata(
            validate=validate.Regexp(r"([\w\W]+[.](xml|yml|yaml)$)|(^$)")
        ),
    )

    name: str = field(default="")
    value_raw: Union[str, bool, int, Dict[Any, Any], List[Any]] = field(
        default="", metadata=metadata(data_key="value")
    )
    # True means this variable can be used in test cases.
    is_case_visible: bool = False

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if self.file and (self.name or self.value_raw):
            raise LisaException(
                f"file cannot be specified with name or value"
                f"file: '{self.file}'"
                f"name: '{self.name}'"
                f"value: '{self.value_raw}'"
            )

        if isinstance(self.value_raw, dict):
            self.value: Union[
                str, bool, int, VariableEntry, List[Union[str, bool, int]]
            ] = load_by_type(VariableEntry, self.value_raw)
        else:
            self.value = self.value_raw


@dataclass_json()
@dataclass
class Notifier(TypedSchema, ExtendableSchemaMixin):
    """
    it sends test progress and results to any place wanted.
    detail types are defined in notifier itself, allowed items are handled in code.
    """

    # A notifier is disabled, if it's false. It helps to disable notifier by
    # variables.
    enabled: bool = True


@dataclass_json()
@dataclass()
class FeatureSettings(
    search_space.RequirementMixin, TypedSchema, ExtendableSchemaMixin
):
    """
    It's the default feature setting. It's used by features without settings,
    and it's the base class of specified settings.
    """

    def __eq__(self, o: object) -> bool:
        assert isinstance(o, FeatureSettings), f"actual: {type(o)}"
        return self.type == o.type

    def __repr__(self) -> str:
        return self.type

    def __hash__(self) -> int:
        return hash(self._get_key())

    @staticmethod
    def create(type: str) -> "FeatureSettings":
        # If a feature has no setting, it will return the default settings.
        return FeatureSettings(type=type)

    def check(self, capability: Any) -> search_space.ResultReason:
        assert isinstance(capability, FeatureSettings), f"actual: {type(capability)}"
        # default FeatureSetting is a place holder, nothing to do.
        result = search_space.ResultReason()
        if self.type != capability.type:
            result.add_reason(
                f"settings are different, "
                f"requirement: {self.type}, capability: {capability.type}"
            )

        return result

    def _get_key(self) -> str:
        return self.type

    def _generate_min_capability(self, capability: Any) -> Any:
        # default FeatureSetting is a place holder, nothing to do.
        return FeatureSettings.create(self.type)


class DiskType(str, Enum):
    PremiumSSDLRS = "PremiumSSDLRS"
    Ephemeral = "Ephemeral"
    StandardHDDLRS = "StandardHDDLRS"
    StandardSSDLRS = "StandardSSDLRS"


def _decode_disk_type(data: Any) -> Any:
    if isinstance(data, dict):
        new_disk_type = search_space.SetSpace[DiskType](is_allow_set=True)
        types = data.get("items", [])
        for item in types:
            new_disk_type.add(DiskType(item))
        decoded_data: Optional[
            Union[search_space.SetSpace[DiskType], DiskType]
        ] = new_disk_type
    elif isinstance(data, str):
        decoded_data = DiskType(data)
    else:
        raise LisaException(f"unkonwn disk_type: {type(data)}")
    return decoded_data


@dataclass_json()
@dataclass()
class DiskOptionSettings(FeatureSettings):
    type: str = constants.FEATURE_DISK
    disk_type: Optional[Union[search_space.SetSpace[DiskType], DiskType]] = field(
        default=DiskType.StandardHDDLRS,
        metadata=metadata(decoder=_decode_disk_type),
    )
    data_disk_count: search_space.CountSpace = field(
        default=search_space.IntRange(min=0),
        metadata=metadata(decoder=search_space.decode_count_space),
    )
    data_disk_caching_type: str = field(
        default=constants.DATADISK_CACHING_TYPE_NONE,
        metadata=metadata(
            validate=validate.OneOf(
                [
                    constants.DATADISK_CACHING_TYPE_NONE,
                    constants.DATADISK_CACHING_TYPE_READONLY,
                    constants.DATADISK_CACHING_TYPE_READYWRITE,
                ]
            ),
        ),
    )
    data_disk_iops: search_space.CountSpace = field(
        default=None,
        metadata=metadata(allow_none=True, decoder=search_space.decode_count_space),
    )
    data_disk_size: search_space.CountSpace = field(
        default=None,
        metadata=metadata(allow_none=True, decoder=search_space.decode_count_space),
    )

    def __eq__(self, o: object) -> bool:
        assert isinstance(o, DiskOptionSettings), f"actual: {type(o)}"
        return (
            self.type == o.type
            and self.disk_type == o.disk_type
            and self.data_disk_count == o.data_disk_count
            and self.data_disk_caching_type == o.data_disk_caching_type
            and self.data_disk_iops == o.data_disk_iops
            and self.data_disk_size == o.data_disk_size
        )

    def __repr__(self) -> str:
        return (
            f"disk_type:{self.disk_type},"
            f"count:{self.data_disk_count},"
            f"caching:{self.data_disk_caching_type},"
            f"iops:{self.data_disk_iops},"
            f"size:{self.data_disk_size}"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def __hash__(self) -> int:
        return super().__hash__()

    def check(self, capability: Any) -> search_space.ResultReason:
        result = super().check(capability)

        result.merge(
            search_space.check_countspace(
                self.data_disk_count, capability.data_disk_count
            ),
            "data_disk_count",
        )
        result.merge(
            search_space.check_countspace(
                self.data_disk_iops, capability.data_disk_iops
            ),
            "data_disk_iops",
        )
        return result

    def _get_key(self) -> str:
        return (
            f"{super()._get_key()}/{self.disk_type}/"
            f"{self.data_disk_count}/{self.data_disk_caching_type}/"
            f"{self.data_disk_iops}/{self.data_disk_size}"
        )

    def _generate_min_capability(self, capability: Any) -> Any:
        assert isinstance(capability, DiskOptionSettings), f"actual: {type(capability)}"
        min_value = DiskOptionSettings()
        if self.data_disk_count or capability.data_disk_count:
            min_value.data_disk_count = search_space.generate_min_capability_countspace(
                self.data_disk_count, capability.data_disk_count
            )
        return min_value


@dataclass_json()
@dataclass()
class FeaturesSpace(
    search_space.SetSpace[Union[str, FeatureSettings]],
):
    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if self.items:
            for index, item in enumerate(self.items):
                if isinstance(item, dict):
                    item = load_by_type(FeatureSettings, item)
                    self.items[index] = item


@dataclass_json()
@dataclass()
class NodeSpace(search_space.RequirementMixin, TypedSchema, ExtendableSchemaMixin):
    type: str = field(
        default=constants.ENVIRONMENTS_NODES_REQUIREMENT,
        metadata=metadata(
            required=True,
            validate=validate.OneOf([constants.ENVIRONMENTS_NODES_REQUIREMENT]),
        ),
    )
    name: str = ""
    is_default: bool = field(default=False)
    node_count: search_space.CountSpace = field(
        default=search_space.IntRange(min=1),
        metadata=metadata(decoder=search_space.decode_count_space),
    )
    core_count: search_space.CountSpace = field(
        default=search_space.IntRange(min=1),
        metadata=metadata(decoder=search_space.decode_count_space),
    )
    memory_mb: search_space.CountSpace = field(
        default=search_space.IntRange(min=512),
        metadata=metadata(decoder=search_space.decode_count_space),
    )
    disk: Optional[DiskOptionSettings] = None
    nic_count: search_space.CountSpace = field(
        default=search_space.IntRange(min=1),
        metadata=metadata(decoder=search_space.decode_count_space),
    )
    gpu_count: search_space.CountSpace = field(
        default=search_space.IntRange(min=0),
        metadata=metadata(decoder=search_space.decode_count_space),
    )
    # all features on requirement should be included.
    # all features on capability can be included.
    _features: Optional[FeaturesSpace] = field(
        default=None,
        metadata=metadata(allow_none=True, data_key="features"),
    )
    # set by requirements
    # capability's is ignored
    _excluded_features: Optional[FeaturesSpace] = field(
        default=None,
        metadata=metadata(
            allow_none=True,
            data_key="excluded_features",
        ),
    )

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        # clarify types to avoid type errors in properties.
        self._features: Optional[search_space.SetSpace[FeatureSettings]]
        self._excluded_features: Optional[search_space.SetSpace[FeatureSettings]]

    def __eq__(self, o: object) -> bool:
        assert isinstance(o, NodeSpace), f"actual: {type(o)}"
        return (
            self.type == o.type
            and self.node_count == o.node_count
            and self.core_count == o.core_count
            and self.memory_mb == o.memory_mb
            and self.disk == o.disk
            and self.nic_count == o.nic_count
            and self.gpu_count == o.gpu_count
            and self.features == o.features
            and self.excluded_features == o.excluded_features
        )

    def __repr__(self) -> str:
        """
        override it for shorter text
        """
        return (
            f"type:{self.type},name:{self.name},"
            f"default:{self.is_default},"
            f"count:{self.node_count},core:{self.core_count},"
            f"mem:{self.memory_mb},disk:{self.disk},"
            f"nic:{self.nic_count},gpu:{self.gpu_count},"
            f"f:{self.features},ef:{self.excluded_features},"
            f"{super().__repr__()}"
        )

    @property
    def features(self) -> Optional[search_space.SetSpace[FeatureSettings]]:
        self._features = self._create_feature_settings_list(self._features)
        if self._features is not None:
            self._features.is_allow_set = True
        return cast(Optional[search_space.SetSpace[FeatureSettings]], self._features)

    @features.setter
    def features(self, value: Optional[search_space.SetSpace[FeatureSettings]]) -> None:
        self._features = cast(FeaturesSpace, value)

    @property
    def excluded_features(self) -> Optional[search_space.SetSpace[FeatureSettings]]:
        if not self._excluded_features:
            self._excluded_features = self._create_feature_settings_list(
                self._excluded_features
            )
            if self._excluded_features is not None:
                self._excluded_features.is_allow_set = False

        return cast(
            Optional[search_space.SetSpace[FeatureSettings]], self._excluded_features
        )

    @excluded_features.setter
    def excluded_features(
        self, value: Optional[search_space.SetSpace[FeatureSettings]]
    ) -> None:
        self._excluded_features = cast(FeaturesSpace, value)

    def check(self, capability: Any) -> search_space.ResultReason:
        result = search_space.ResultReason()
        if capability is None:
            result.add_reason("capability shouldn't be None")

        if self.features:
            assert self.features.is_allow_set, "features should be allow set"
        if self.excluded_features:
            assert (
                not self.excluded_features.is_allow_set
            ), "excluded_features shouldn't be allow set"

        assert isinstance(capability, NodeSpace), f"actual: {type(capability)}"

        if (
            not capability.node_count
            or not capability.core_count
            or not capability.memory_mb
            or not capability.nic_count
        ):
            result.add_reason(
                "node_count, core_count, memory_mb, nic_count "
                "shouldn't be None or zero."
            )

        if isinstance(self.node_count, int) and isinstance(capability.node_count, int):
            if self.node_count > capability.node_count:
                result.add_reason(
                    f"capability node count {capability.node_count} "
                    f"must be more than requirement {self.node_count}"
                )
        else:
            result.merge(
                search_space.check_countspace(self.node_count, capability.node_count),
                "node_count",
            )

        result.merge(
            search_space.check_countspace(self.core_count, capability.core_count),
            "core_count",
        )
        result.merge(
            search_space.check_countspace(self.memory_mb, capability.memory_mb),
            "memory_mb",
        )
        if self.disk:
            result.merge(self.disk.check(capability.disk))
        result.merge(
            search_space.check_countspace(self.nic_count, capability.nic_count),
            "nic_count",
        )
        result.merge(
            search_space.check_countspace(self.gpu_count, capability.gpu_count),
            "gpu_count",
        )
        if self.features:
            for feature in self.features:
                cap_feature = self._find_feature_by_type(
                    feature.type, capability.features
                )
                if cap_feature:
                    result.merge(feature.check(cap_feature))
                else:
                    result.add_reason(
                        f"no feature '{feature.type}' found in capability"
                    )
        if self.excluded_features:
            for feature in self.excluded_features:
                cap_feature = self._find_feature_by_type(
                    feature.type, capability.excluded_features
                )
                if cap_feature:
                    result.add_reason(
                        f"excluded feature '{feature.type}' found in capability"
                    )

        return result

    def expand_by_node_count(self) -> List[Any]:
        # expand node count in requirement to one,
        # so that's easy to compare equalization later.
        expanded_requirements: List[NodeSpace] = []
        node_count = search_space.generate_min_capability_countspace(
            self.node_count, self.node_count
        )
        for _ in range(node_count):
            expanded_copy = copy.copy(self)
            expanded_copy.node_count = 1
            expanded_requirements.append(expanded_copy)
        return expanded_requirements

    def has_feature(self, find_type: str) -> bool:
        result = False
        if not self.features:
            return result

        return any(feature for feature in self.features if feature.type == find_type)

    def _generate_min_capability(self, capability: Any) -> Any:
        # copy to duplicate extended schema
        min_value: NodeSpace = copy.deepcopy(self)
        assert isinstance(capability, NodeSpace), f"actual: {type(capability)}"

        if self.node_count or capability.node_count:
            if isinstance(self.node_count, int) and isinstance(
                capability.node_count, int
            ):
                # capability can have more node
                min_value.node_count = capability.node_count
            else:
                min_value.node_count = search_space.generate_min_capability_countspace(
                    self.node_count, capability.node_count
                )
        else:
            raise LisaException("node_count cannot be zero")
        if self.core_count or capability.core_count:
            min_value.core_count = search_space.generate_min_capability_countspace(
                self.core_count, capability.core_count
            )
        else:
            raise LisaException("core_count cannot be zero")
        if self.memory_mb or capability.memory_mb:
            min_value.memory_mb = search_space.generate_min_capability_countspace(
                self.memory_mb, capability.memory_mb
            )
        else:
            raise LisaException("memory_mb cannot be zero")
        if self.disk or capability.disk:
            min_value.disk = search_space.generate_min_capability(
                self.disk, capability.disk
            )

        if self.nic_count or capability.nic_count:
            min_value.nic_count = search_space.generate_min_capability_countspace(
                self.nic_count, capability.nic_count
            )
        else:
            raise LisaException("nic_count cannot be zero")
        if self.gpu_count or capability.gpu_count:
            min_value.gpu_count = search_space.generate_min_capability_countspace(
                self.gpu_count, capability.gpu_count
            )
        else:
            min_value.gpu_count = 0

        if capability.features:
            min_value.features = search_space.SetSpace[FeatureSettings](
                is_allow_set=True
            )
            for original_cap_feature in capability.features:
                capability_feature = self._get_or_create_feature_settings(
                    original_cap_feature
                )
                requirement_feature = (
                    self._find_feature_by_type(capability_feature.type, self.features)
                    or capability_feature
                )
                min_feature = requirement_feature.generate_min_capability(
                    capability_feature
                )
                min_value.features.add(min_feature)
        if capability.excluded_features:
            # TODO: the min value for excluded feature is not clear. It may need
            # to be improved with real scenarios.
            min_value.excluded_features = search_space.SetSpace[FeatureSettings](
                is_allow_set=False
            )
            for original_cap_feature in capability.excluded_features:
                capability_feature = self._get_or_create_feature_settings(
                    original_cap_feature
                )
                requirement_feature = (
                    self._find_feature_by_type(
                        capability_feature.type, self.excluded_features
                    )
                    or capability_feature
                )
                min_feature = requirement_feature.generate_min_capability(
                    capability_feature
                )
                min_value.excluded_features.add(min_feature)
        return min_value

    def _find_feature_by_type(
        self,
        find_type: str,
        features: Optional[search_space.SetSpace[Any]],
    ) -> Optional[FeatureSettings]:
        result: Optional[FeatureSettings] = None
        if not features:
            return result

        is_found = False
        for original_feature in features.items:
            feature = self._get_or_create_feature_settings(original_feature)
            if feature.type == find_type:
                is_found = True
                break
        if is_found:
            result = feature

        return result

    def _create_feature_settings_list(
        self, features: Optional[search_space.SetSpace[Any]]
    ) -> Optional[FeaturesSpace]:
        result: Optional[FeaturesSpace] = None
        if features is None:
            return result

        result = cast(
            FeaturesSpace,
            search_space.SetSpace[FeatureSettings](is_allow_set=features.is_allow_set),
        )
        for raw_feature in features.items:
            feature = self._get_or_create_feature_settings(raw_feature)
            result.add(feature)

        return result

    def _get_or_create_feature_settings(self, feature: Any) -> FeatureSettings:
        if isinstance(feature, str):
            feature_setting = FeatureSettings.create(feature)
        elif isinstance(feature, FeatureSettings):
            feature_setting = feature
        else:
            raise LisaException(
                f"unsupported type {type(feature)} found in features, "
                "only str and FeatureSettings supported."
            )
        return feature_setting


@dataclass_json()
@dataclass
class Capability(NodeSpace):
    type: str = constants.ENVIRONMENTS_NODES_REQUIREMENT

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        super().__post_init__(*args, **kwargs)
        self.node_count = 1


@dataclass_json()
@dataclass
class Node(TypedSchema, ExtendableSchemaMixin):
    capability: Capability = field(default_factory=Capability)
    name: str = ""
    is_default: bool = field(default=False)


@dataclass_json()
@dataclass
class LocalNode(Node):
    type: str = constants.ENVIRONMENTS_NODES_LOCAL


@dataclass_json()
@dataclass
class RemoteNode(Node):
    type: str = constants.ENVIRONMENTS_NODES_REMOTE
    address: str = ""
    port: int = field(
        default=22,
        metadata=metadata(
            field_function=fields.Int, validate=validate.Range(min=1, max=65535)
        ),
    )
    public_address: str = ""
    public_port: int = field(
        default=22,
        metadata=metadata(
            field_function=fields.Int, validate=validate.Range(min=1, max=65535)
        ),
    )
    username: str = constants.DEFAULT_USER_NAME
    password: str = ""
    private_key_file: str = ""

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        add_secret(self.username, PATTERN_HEADTAIL)
        add_secret(self.password)
        add_secret(self.private_key_file)


@dataclass_json()
@dataclass
class Environment:
    name: str = field(default="")
    topology: str = field(
        default=constants.ENVIRONMENTS_SUBNET,
        metadata=metadata(validate=validate.OneOf([constants.ENVIRONMENTS_SUBNET])),
    )
    nodes_raw: Optional[List[Any]] = field(
        default=None,
        metadata=metadata(data_key=constants.NODES),
    )
    nodes_requirement: Optional[List[NodeSpace]] = None

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        results: List[Node] = []

        if self.nodes_raw:
            for node_raw in self.nodes_raw:
                node_type = node_raw[constants.TYPE]
                if node_type == constants.ENVIRONMENTS_NODES_REQUIREMENT:
                    original_req: NodeSpace = load_by_type(NodeSpace, node_raw)
                    expanded_req = original_req.expand_by_node_count()
                    if self.nodes_requirement is None:
                        self.nodes_requirement = []
                    self.nodes_requirement.extend(expanded_req)
                else:
                    # load base schema for future parsing
                    node: Node = load_by_type(Node, node_raw)
                    results.append(node)
            self.nodes_raw = None

        self.nodes = results


@dataclass_json()
@dataclass
class EnvironmentRoot:
    warn_as_error: bool = field(default=False)
    environments: List[Environment] = field(default_factory=list)


@dataclass_json()
@dataclass
class Platform(TypedSchema, ExtendableSchemaMixin):
    type: str = field(
        default=constants.PLATFORM_READY,
        metadata=metadata(required=True),
    )

    admin_username: str = constants.DEFAULT_USER_NAME
    admin_password: str = ""
    admin_private_key_file: str = ""

    # no/False: means to delete the environment regardless case fail or pass
    # yes/always/True: means to keep the environment regardless case fail or pass
    keep_environment: Optional[Union[str, bool]] = constants.ENVIRONMENT_KEEP_NO

    # platform can specify a default environment requirement
    requirement: Optional[Dict[str, Any]] = None

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        add_secret(self.admin_username, PATTERN_HEADTAIL)
        add_secret(self.admin_password)

        if self.type != constants.PLATFORM_READY:
            if self.admin_password and self.admin_private_key_file:
                raise LisaException(
                    "only one of admin_password and admin_private_key_file can be set"
                )
            elif not self.admin_password and not self.admin_private_key_file:
                raise LisaException(
                    "one of admin_password and admin_private_key_file must be set"
                )

        if isinstance(self.keep_environment, bool):
            if self.keep_environment:
                self.keep_environment = constants.ENVIRONMENT_KEEP_ALWAYS
            else:
                self.keep_environment = constants.ENVIRONMENT_KEEP_NO
        allow_list = [
            constants.ENVIRONMENT_KEEP_ALWAYS,
            constants.ENVIRONMENT_KEEP_FAILED,
            constants.ENVIRONMENT_KEEP_NO,
        ]
        assert isinstance(self.keep_environment, str), (
            f"keep_environment should be {allow_list} or bool, "
            f"but it's {type(self.keep_environment)}, '{self.keep_environment}'"
        )
        if isinstance(self.keep_environment, str):
            self.keep_environment = self.keep_environment.lower()
            if self.keep_environment not in allow_list:
                raise LisaException(
                    f"keep_environment only can be set as one of {allow_list}"
                )

        # this requirement in platform will be applied to each test case
        # requirement. It means the set value will override value in test cases.
        # But the schema will be validated here. The original NodeSpace object holds
        if self.requirement:
            # validate schema of raw inputs
            load_by_type(Capability, self.requirement)


@dataclass_json()
@dataclass
class Criteria:
    """
    all rules in same criteria are AND condition.
    we may support richer conditions later.
    match case by name pattern
    """

    name: Optional[str] = None
    area: Optional[str] = None
    category: Optional[str] = None
    # the runbook is complex to convert, so manual overwrite it in __post_init__.
    priority: Optional[Union[int, List[int]]] = field(
        default=None,
        metadata=metadata(
            validate=ListableValidator(int, validate.Range(min=0, max=4))
        ),
    )
    # tags is a simple way to include test cases within same topic.
    tags: Optional[Union[str, List[str]]] = field(
        default=None, metadata=metadata(validate=ListableValidator(str))
    )


@dataclass_json()
@dataclass
class BaseTestCaseFilter(TypedSchema, ExtendableSchemaMixin, BaseClassMixin):
    """
    base test case filters for subclass factory
    """

    type: str = field(
        default=constants.TESTCASE_TYPE_LISA,
    )
    # if it's false, current filter is ineffective.
    enable: bool = field(default=True)


@dataclass_json()
@dataclass
class TestCase(BaseTestCaseFilter):
    type: str = field(
        default=constants.TESTCASE_TYPE_LISA,
        metadata=metadata(
            validate=validate.OneOf([constants.TESTCASE_TYPE_LISA]),
        ),
    )
    name: str = ""
    criteria: Optional[Criteria] = None
    # specify use this rule to select or drop test cases. if it's forced include or
    # exclude, it won't be effect by following select actions. And it fails if
    # there are force rules conflict.
    select_action: str = field(
        default=constants.TESTCASE_SELECT_ACTION_INCLUDE,
        metadata=config(
            mm_field=fields.String(
                validate=validate.OneOf(
                    [
                        # none means this action part doesn't include or exclude cases
                        constants.TESTCASE_SELECT_ACTION_NONE,
                        constants.TESTCASE_SELECT_ACTION_INCLUDE,
                        constants.TESTCASE_SELECT_ACTION_FORCE_INCLUDE,
                        constants.TESTCASE_SELECT_ACTION_EXCLUDE,
                        constants.TESTCASE_SELECT_ACTION_FORCE_EXCLUDE,
                    ]
                )
            ),
        ),
    )
    # run this group of test cases several times
    # default is 1
    times: int = field(
        default=1,
        metadata=metadata(field_function=fields.Int, validate=validate.Range(min=1)),
    )
    # retry times if fails. Default is 0, not to retry.
    retry: int = field(
        default=0,
        metadata=metadata(field_function=fields.Int, validate=validate.Range(min=0)),
    )
    # each case with this rule will be run in a new environment.
    use_new_environment: bool = False
    # Once it's set, failed test result will be rewrite to success
    # it uses to work around some cases temporarily, don't overuse it.
    # default is false
    ignore_failure: bool = False
    # case should run on a specified environment
    environment: str = ""

    @classmethod
    def type_name(cls) -> str:
        return constants.TESTCASE_TYPE_LISA


@dataclass_json()
@dataclass
class LegacyTestCase(BaseTestCaseFilter):
    type: str = field(
        default=constants.TESTCASE_TYPE_LEGACY,
        metadata=metadata(
            required=True,
            validate=validate.OneOf([constants.TESTCASE_TYPE_LEGACY]),
        ),
    )

    repo: str = "https://github.com/microsoft/lisa.git"
    branch: str = "master"
    command: str = ""

    @classmethod
    def type_name(cls) -> str:
        return constants.TESTCASE_TYPE_LEGACY


@dataclass_json()
@dataclass
class Runbook:
    # run name prefix to help grouping results and put it in title.
    name: str = "not_named"
    test_project: str = ""
    test_pass: str = ""
    tags: Optional[List[str]] = None
    concurrency: int = 1
    include: Optional[List[Include]] = field(default=None)
    extension: Optional[List[Union[str, Extension]]] = field(default=None)
    variable: Optional[List[Variable]] = field(default=None)
    transformer: Optional[List[Transformer]] = field(default=None)
    combinator: Optional[Combinator] = field(default=None)
    environment: Optional[EnvironmentRoot] = field(default=None)
    notifier: Optional[List[Notifier]] = field(default=None)
    platform: List[Platform] = field(default_factory=list)
    #  will be parsed in runner.
    testcase_raw: List[Any] = field(
        default_factory=list, metadata=metadata(data_key=constants.TESTCASE)
    )

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if not self.platform:
            self.platform = [Platform(type=constants.PLATFORM_READY)]
        if not self.testcase_raw:
            self.testcase_raw = [
                {
                    constants.TESTCASE_CRITERIA: {
                        constants.TESTCASE_CRITERIA_AREA: "demo"
                    }
                }
            ]
        self.testcase: List[Any] = []


def load_by_type(schema_type: Type[T], raw_runbook: Any, many: bool = False) -> T:
    """
    Convert dict, list or base typed schema to specified typed schema.
    """
    if type(raw_runbook) == schema_type:
        return raw_runbook

    if not isinstance(raw_runbook, dict) and not many:
        raw_runbook = raw_runbook.to_dict()

    result: T = schema_type.schema().load(raw_runbook, many=many)  # type: ignore
    return result


def load_by_type_many(schema_type: Type[T], raw_runbook: Any) -> List[T]:
    """
    Convert raw list to list of typed schema. It has different returned type
    with load_by_type.
    """
    result = load_by_type(schema_type, raw_runbook=raw_runbook, many=True)
    return cast(List[T], result)
