from typing import Generic, TypeVar, Union, Any
from dataclasses import dataclass

T = TypeVar('T')

@dataclass(frozen=True)
class Success(Generic[T]):
    data: T
    
    @property
    def is_success(self) -> bool:
        return True

@dataclass(frozen=True)
class Failure:
    error: Exception
    
    @property
    def is_success(self) -> bool:
        return False

Result = Union[Success[T], Failure]
