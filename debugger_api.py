from __future__ import annotations
from abc import abstractmethod, ABC 
from typing import List, Union
from enum import Enum, IntEnum

class SymbolType(Enum):
    """
    Specifies the type of the symbol.
    """
    BASIC="basic"
    STRUCT="structure"
    ARRAY="array"
    POINTER="pointer"

class Symbol(ABC):
    """
    Represents a symbol in a C-like program which contains either a basic
    value such an integer or string, or could represent a structure or array
    that contain members or indices which themselves can be treated as
    symbols.

    Symbols can be of the following types:

    - Structure Symbols for which is_struct() returns True contains members
      (which are of Symbol type) indexed by name. Members can be retrieved by
      name using the member() API.
    - Array Symbols for which is_array() returns True contains indices
      (which are of Symbol type) indexed by integers. The total number of
      indices can be retrived by using the num_indices() API.
    - Basic Symbols for which is_basic() returns True which contains neither
      members or elements. They hold either integers or strings that can be
      retrieved by calling the value() API.

    Each Symbol has a tree like structure that terminates in a basic symbol.
    """
    def __repr__(self):
        return self.name()

    @abstractmethod
    def name(self) -> str:
        """
        Name of this symbol

        :return returns the name of this symbol.
        """

    @abstractmethod
    def type(self) -> SymbolType:
        """
        Type of this symbol.

        :return returns the type of this symbol.
        """

    def is_basic(self) -> bool:
        """
        Checks if this symbol is a basic symbol. Basic variables do not
        have members or indices and only support the value method which returns
        the value of the symbol which could be integers or strings.

        :return True if the symbol is of basic type (i.e., has no members or indices).
        """
        return self.type() == SymbolType.BASIC

    def is_pointer(self) -> bool:
        """
        Checks if this symbol is a pointer symbol. A pointer symbol allows deferencing.
        
        :return True if the symbol is a pointer type.
        """
        return self.type() == SymbolType.POINTER

    @abstractmethod 
    def value(self) -> Union[str,int,float]: 
        """
        For a basic symbol (is_basic() is True), returns the value of the symbol. 

        :return The value of a basic symbol.
        """

    @abstractmethod 
    def members(self) -> List[Symbol]:
        """
        Return all members contained within this symbol. Basic variables for
        which is_basic() returns True do not have members. Calling this
        function on such variables will raise a NotSupported exception.

        :returns A list of members contained in this symbol.
        """

    @abstractmethod 
    def member(self, name: str) -> Symbol: 
        """
        A member symbol with the given name. Raises NotSupported exception if the
        symbol is a basic type or if the member name doesn't exist.

        :return Member Symbol with the specified name.
        """

    @abstractmethod 
    def has_member(self, name: str) -> bool:
        """
        Check if a member exists in this symbol.

        :returns True of the symbol contains the member with a given name.
        """

    @abstractmethod 
    def num_indices(self) -> int:
        """
        For an array type symbol, returns the total number of array elements. 

        :returns Number of elements in a array type symbol (i.e., a symbol with is_array() == True)
        """

    @abstractmethod 
    def index(self, n: int) -> Symbol:
        """
        For an array symbol (is_array() is True), returns the symbol at
        index `n`. `n` must be less than or equal to num_indices().

        :return Symbol at index n.
        """

class ProcessState(IntEnum):
    INVALID   = 0
    UNLOADED  = 1
    CONNECTED = 2
    ATTACHING = 3
    LAUNCHING = 4
    STOPPED   = 5
    RUNNING   = 6
    STEPPING  = 7
    CRASHED   = 8
    DETACHED  = 9
    EXITED    = 10
    SUSPENDED = 11

class Target(ABC): 
    """
    Represents a debugger target that contains the memory dump of a processor
    along with its program image. This allows users to read variables from the
    target.
    """

    @abstractmethod
    def name(self) -> str:
        """
        Returns the target's name.

        :return Name of this target.
        """

    def set_breakpoint_by_location(self, filename: str, line: str):
        """
        Sets a breakpoint based based on the provided file and line.

        @todo Extend this so that it returns a breakpoint object that can be
        manipulated using LLMs.
        """
        raise NotImplementedError("This target doesn't support setting breakpoint by location")

    def set_breakpoint_by_label(self, label: str):
        raise NotImplementedError("This target doesn't support setting breakpoint by label")

    def launch_process(self) -> ProcessState:
        """
        Launches a process associated with the executable.
        """
        raise NotImplementedError("This target does not support launching processess")

    @abstractmethod 
    def globals(self) -> List[Symbol]:
        """
        Returns all global variables contained this target.

        :return A list of variables contained in the current target. 
        """

    @abstractmethod 
    def get_global(self, name:str) -> Symbol: 
        """
        Returns the global symbol with the given name.

        :return Returns the symbol with the given name.
        """

class Debugger(ABC):
    """
    A debugger is a top-level object thtat represents a collection of targets
    each representing the memory dump of a processor memory along with its
    program image.
    """

    @abstractmethod
    def targets(self) -> List[Target]:
        """
        Returns the list of all targets in this crash dump.

        :return A list of targets contained in this Debugger.
        """

    @abstractmethod
    def create_target_from_file(self, name, file_path) -> Target:
        """
        Create a target with the specified name by loading a file from the
        specified path.
        """

    @abstractmethod 
    def target(self, name: str) -> Target: 
        """
        Returns the target with the specfied name.

        :return The target with the specified name.
        """

class Crashdump(Debugger):
    """
    A crash dump is synonymous to a debugger.
    """
