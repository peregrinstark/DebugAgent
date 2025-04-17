from typing import List, Dict, Optional, Union
import pdb
import IPython
import lldb
from debugger_api import Debugger, Target, Symbol, ProcessState, SymbolType
from enum import IntEnum
from enum import IntEnum

class LLDBSymbol(Symbol):

    def __init__(self, var: lldb.SBValue):
        self._var = var

    def name(self) -> str:
        return self._var.name

    def type(self) -> SymbolType:
        """
        Returns the type of this symbol.
        """
        can_type = self._var.GetType().GetCanonicalType()
        if can_type.IsPointerType():
            return SymbolType.POINTER
        elif can_type.IsArrayType():
            return SymbolType.ARRAY
        elif can_type.IsAggregateType():
            return SymbolType.STRUCT
        else:
            return SymbolType.BASIC

    def value(self) -> Union[str, int, float]: 
        """
        For a basic or pointer symbol, returns its value. For a pointer, the
        value is the address held by the pointer symbol.

        :return The value of the symbol.
        """
        if self.type() == SymbolType.POINTER:
            return int(self._var.GetValue(), 0)

        assert self.type() == SymbolType.BASIC

        # these are integer types.
        int_types = {
                lldb.eBasicTypeSignedChar,
                lldb.eBasicTypeUnsignedChar,
                lldb.eBasicTypeChar,
                lldb.eBasicTypeInt,
                lldb.eBasicTypeLong,
                lldb.eBasicTypeUnsignedInt,
                lldb.eBasicTypeUnsignedLong,
                lldb.eBasicTypeLongLong,
                lldb.eBasicTypeUnsignedLongLong
                }
        # floating point types.
        float_types = {
                lldb.eBasicTypeFloat,
                lldb.eBasicTypeDouble
                }

        # get the canonical type ...
        can_type = self._var.GetType().GetCanonicalType()
        # ... and convert it into a basic type.
        basic_type = can_type.GetBasicType()

        # get the value of the variable.
        if basic_type == lldb.eBasicTypeInvalid:
            raise ValueError(f'{can_type} is not a basic type!')
        elif basic_type in { lldb.eBasicTypeSignedChar, lldb.eBasicTypeChar }:
            return int(self._var.GetValueAsSigned())
        elif basic_type == lldb.eBasicTypeUnsignedChar:
            return int(self._var.GetValueAsUnsigned())
        elif basic_type in int_types:
            return int(self._var.GetValue(), 0)
        elif basic_type in float_types:
            return float(self._var.GetValue())
        else:
            raise NotImplementedError(f'{can_type} is an unknown type!')

    def has_members(self) -> bool:
        """
        Check if this symbol is a structure type. A structure type symbol contains members.

        :return True if this symbol is of structure type.
        """
        can_type = self._var.GetType().GetCanonicalType()
        return can_type.IsAggregateType() and not can_type.IsArrayType()

    def _check_members(self):

        if not self.has_members():
            raise RuntimeError(f'{self.name()} is not a structure or union type!')

    def _check_array(self):

        can_type = self._var.GetType().GetCanonicalType()
        return can_type.IsArrayType()

    def num_members(self) -> int:
        """
        Returns the number of members that are contained within this symbol.

        :returns The total number of members within this symbol.
        """
        self._check_members()
        return self._var.GetNumChildren()

    def members(self) -> List[Symbol]:
        """
        Return all members contained within this symbol. Basic variables for
        which is_basic() returns True do not have members. Calling this
        function on such variables will raise a NotSupported exception.

        :returns A list of members contained in this symbol.
        """
        self._check_members()
        members: List[Symbol] = []
        for idx in range(self.num_members()):
            members.append(
                    LLDBSymbol(self._var.GetChildAtIndex(idx))
                    )
        return members

    def member(self, name: str) -> Symbol: 
        """
     a member symbol with the given name. Raises NotSupported
        exception if the symbol is a basic type or if the member name doesn't
        exist.

        :return Member Symbol with the specified name.
        """
        self._check_members()
        return LLDBSymbol(self._var.GetChildMemberWithName(name))

    def has_member(self, name: str) -> bool:
        """
        Check if a member exists in this symbol.

        :returns True of the symbol contains the member with a given name.
        """
        self._check_members()
        for idx in range(self.num_members()):
            if self._var.GetChildAtIndex(idx).GetName() == name:
                return True
        return False
        
    def num_indices(self) -> int:
        """
        For an array type symbol, returns the total number of array elements. 

        :returns Number of elements in a array type symbol (i.e., a symbol with is_array() == True)
        """
        assert self.type() == SymbolType.ARRAY 
        return self._var.GetNumChildren()

    def index(self, n: int) -> Symbol:
        """
        For an array symbol (is_array() is True), returns the symbol at
        index `n`. `n` must be less than or equal to num_indices().

        :return Symbol at index n.
        """
        assert self.type() == SymbolType.ARRAY
        assert n < self.num_indices()
        return LLDBSymbol(self._var.GetChildAtIndex(n))

LLDBProcessMapDict = {
        lldb.eStateInvalid  :  ProcessState.INVALID, 
        lldb.eStateUnloaded :  ProcessState.UNLOADED, 
        lldb.eStateConnected:  ProcessState.CONNECTED, 
        lldb.eStateAttaching:  ProcessState.ATTACHING, 
        lldb.eStateLaunching:  ProcessState.LAUNCHING, 
        lldb.eStateStopped  :  ProcessState.STOPPED, 
        lldb.eStateRunning  :  ProcessState.RUNNING, 
        lldb.eStateStepping :  ProcessState.STEPPING, 
        lldb.eStateCrashed  :  ProcessState.CRASHED, 
        lldb.eStateDetached :  ProcessState.DETACHED, 
        lldb.eStateExited   :  ProcessState.EXITED, 
        lldb.eStateSuspended:  ProcessState.SUSPENDED
        }

class LLDBTarget(Target):

    def __init__(self, name: str, target: lldb.SBTarget, debugger):
        self._target = target
        self._name = name
        self._debugger = debugger
        self._bps_label: Dict[str, lldb.SBBreakpoint] = {}
        self._process: Optional[lldb.SBProcess] = None

    def name(self):
        return self._name

    def set_breakpoint_by_label(self, label:str):
        """
        @todo 

        - Create a new breakpoint abstraction that provides breakpoint related
          functionality.
        """
        self._bps_label[label] = self._target.BreakpointCreateByName(label)

    def launch_process(self) -> ProcessState:
        _ = lldb.SBError()
        self._process = self._target.LaunchSimple(None, None, ".")
        assert self._process
        return LLDBProcessMapDict[self._process.GetState()]

    def globals(self) -> List[Symbol]:
        var_list = self._target.FindGlobalVariables(".*", 32768, lldb.eMatchTypeRegex)
        vars: List[Symbol] = []
        for idx in range(var_list.GetSize()):
            vars.append(LLDBSymbol(var_list.GetValueAtIndex(idx)))
        return vars

    def get_global(self, name: str) -> LLDBSymbol:
        var = self._target.FindFirstGlobalVariable(name)
        return LLDBSymbol(var)

    def get_backtrace(self):
        frames = []
        assert self._process
        thread = self._process.GetSelectedThread()
        for frame in thread:
            file = frame.GetLineEntry().GetFileSpec().GetFilename()
            line = frame.GetLineEntry().GetLine()
            if file is not None:
                frames.append(f"{frame.GetFunctionName()} at {file}:{line}")
            else:
                frames.append(frame.GetFunctionName())
        return "\n".join(frames)
    

class LLDB(Debugger):

    def __init__(self):
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.SetAsync(False)
        self._targets: Dict[str, LLDBTarget] = {}
    
    def create_target_from_file(self, name, file_path) -> LLDBTarget:
        lldb_target = self.debugger.CreateTargetWithFileAndArch(file_path, lldb.LLDB_ARCH_DEFAULT)
        _target = LLDBTarget(name, lldb_target, self)
        self._targets[name] = _target
        return _target
    
    def target(self, name: str):
        return self._targets[name]

    def targets(self) -> List[Target]:
        return list(self._targets.values())
