from typing import Any

from .assertpy import AssertionBuilder

class BaseMixin:
    description: Any = ...
    def described_as(self, description: Any) -> AssertionBuilder: ...
    def is_equal_to(self, other: Any, **kwargs: Any) -> AssertionBuilder: ...
    def is_not_equal_to(self, other: Any) -> AssertionBuilder: ...
    def is_same_as(self, other: Any) -> AssertionBuilder: ...
    def is_not_same_as(self, other: Any) -> AssertionBuilder: ...
    def is_true(self) -> AssertionBuilder: ...
    def is_false(self) -> AssertionBuilder: ...
    def is_none(self) -> AssertionBuilder: ...
    def is_not_none(self) -> AssertionBuilder: ...
    def is_type_of(self, some_type: Any) -> AssertionBuilder: ...
    def is_instance_of(self, some_class: Any) -> AssertionBuilder: ...
    def is_length(self, length: Any) -> AssertionBuilder: ...
