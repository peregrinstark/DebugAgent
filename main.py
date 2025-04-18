import sys

import IPython
from lldb_wrapper import LLDB
from debugger_api import ProcessState, Symbol, SymbolType
from typing import List, Tuple, Literal, Any, Dict, Union
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool, StructuredTool, ToolException
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import tools_condition, ToolNode, create_react_agent
import uuid

class SymbolInfo(BaseModel):
    """
    Represents a symbol in a C-like program which contains either a basic
    value such an integer or string, or could represent a structure or array
    that contain members or indices which themselves can be treated as
    symbols.

    Each symbol has a unique UUID identifier which can be used to uniquely
    refer to this symbol, and a type that is described below:

    - Structure Symbols for which type is "structure" contains members (which
      are in turn of Symbol type) indexed by name. Members can be retrieved by
      name using the get_member() tool.
    - Array Symbols for which type is "array" are arrays of Symbols that can be
      indexed using integers. The total number of indices can be retrived by
      using the get_num_indices() tool and a Symbol at a specific index can be
      retrieved using get_index() tool.
    - String Synbols for which type is "string" contains string values which
      can be retrieved using get_value_string().
    - Basic Symbols for which type is "basic" contains basic values such as
      integers or floating point values. Their value can be retrieved using
      get_value_number().
    - Pointer Symbols, which contain an address of another Symbol. The address
      can be retrieved using get_value_number().
    - Enum Symbols, which represent an enumeration. You can retrieve the enum
      name using get_value_string() and the enum value (an unsigned integer)
      using get_value_number(). Enums contain both a name and value and is
      typically represented as "name(value").

    Each symbol that isn't one of "basic", "enum" or "pointer" can be traversed
    recursively. Structures can be traversed by enumerating its members and
    Arrays can be traversed by enumerating its indices. 
    """
    id: uuid.UUID = Field(..., description="Unique identifier for this symbol")
    name: str = Field(..., description="Name of the symbol.")
    type: Literal['basic', 'structure', 'array', 'pointer', 'string', 'enum']

class TargetInfo(BaseModel):
    """
    Represents a LLDB target. A target can be uniquely identified using its
    name.
    """
    name: str = Field(..., description="Name of the target")

class Application:

    def __init__(self):
        self.lldb = LLDB()
        self.symbols: Dict[uuid.UUID, Symbol]  = {}

    def add_symbol(self, sym: Symbol) -> SymbolInfo:
        id = uuid.uuid4()
        self.symbols[id] = sym
        return SymbolInfo(id=id, name=sym.name(), type=sym.type().value)

debugger = Application()

@tool(parse_docstring=True)
def create_target_from_file(name: str, exe_file: str) -> TargetInfo:
    """
    Given an executable file, create a new LLDB target.

    Args:
        exe_file: Executable file for the target.
    """
    debugger.lldb.create_target_from_file(name, exe_file)
    return TargetInfo(name=name)

@tool(parse_docstring=True)
def set_breakpoint_from_label(target: TargetInfo, label: str) -> bool:
    """
    Sets a breakpoint on the specified target at the provided label which could
    be a function name.

    Args:
        target: The target to set the breakpoint on.
        label: The label at which to set the breakpoint.

    Return:
        True if setting breakpoints succeeded.
    """
    debugger.lldb.target(target.name).set_breakpoint_by_label(label)
    return True

@tool(parse_docstring=True)
def launch_process(target: TargetInfo) -> str:
    """
    Starts (runs) the program by creating a process.
    
    If the programs run and stops at a breakpoint, return's the stack trace of
    the current running thread, otherwise, just returns a success message.

    Args:
        target: The target name to launch.
    """
    _target = debugger.lldb.target(target.name)
    state = _target.launch_process()
    if state == ProcessState.STOPPED:
        return _target.get_backtrace()
    return "The process was successfully launched."

@tool(parse_docstring=True)
def get_global(target: TargetInfo, name: str) -> SymbolInfo:
    """
    Returns a global variable read from the target. A variable is a Symbol with
    a type defined by SymbolType.

    Args:
        target: Name of the target to read variable from.
        name: Name of the global variable to fetch.

    Returns:
        A Symbol
    """
    # get the target.
    _target = debugger.lldb.target(target.name)
    # get the variable from the target.
    var = _target.get_global(name)
    # append this object with a unique UUID to our application database.
    return debugger.add_symbol(var)

def get_member(sym: SymbolInfo, name: str) -> SymbolInfo:
    """
    Gets the member of a Symbol, which is itself a Symbol. A Symbol (or
    variable) can have members only if its type is SymbolType.STRUCT.

    Args:
        sym: The Symbol whose member needs to be read.
        name: The name of the member within the symbol.

    Returns:
        A Symbol that contains the member with the specified name within the
        specified Struct Symbol.
    """
    var = debugger.symbols[sym.id]
    if var.type() != SymbolType.STRUCT:
        raise ToolException(f'{sym.name} is not a structure type. It does not have members!')
    memb = var.member(name)
    return debugger.add_symbol(memb)

get_member_tool = StructuredTool.from_function(
        func=get_member,
        handle_tool_error=True
        )

def get_members(sym: SymbolInfo) -> List[SymbolInfo]:
    """
    Gets all members of a given Symbol. Only symbols that are type 'structure'
    have members.

    Args:
        sym: The Symbol whose members are requested.

    Returns:
        A list of members each of which is itself a Symbol.
    """
    var = debugger.symbols[sym.id]
    if var.type() != SymbolType.STRUCT:
        raise ToolException('{sym.name} is not a structure type. It does not have members!')
    syms = []
    for m in var.members():
        syms.append(debugger.add_symbol(m))
    return syms

get_members_tool = StructuredTool.from_function(
        func=get_members,
        handle_tool_error=True
        )

def get_index(sym: SymbolInfo, index: int) -> SymbolInfo:
    """
    Gets the Symbol at a given index of a parent array Symbol. A Symbol is an
    array if its type is SymbolType.ARRAY. Array symbols can be indexed using
    an integer and its length can be queried using the get_array_size() tool.

    Args:
        sym: The Array Symbol which needs to be indexed.
        index: The index within the Array Symbol that needs to be fetched.

    Returns:
        A Symbol at the provided index within the specified Array Symbol.
    """
    var = debugger.symbols[sym.id]
    if var.type() != SymbolType.ARRAY:
        raise ToolException(f'get_index(...) only works on array type symbols!')
    idx_var = var.index(index)
    return debugger.add_symbol(idx_var)

get_index_tool = StructuredTool.from_function(
        func=get_index,
        handle_tool_error=True
        )

def get_array_size(sym: SymbolInfo) -> int:
    """
    Given an array symbol, returns the number of elements of the array. A
    symbol is an array symbol only if its type is "array".

    Args:
        sym: An array symbol whose size needs to be known.

    Returns:
        Length of the array symbol (i.e., number of elements).
    """
    var = debugger.symbols[sym.id]
    if var.type() != SymbolType.ARRAY:
        raise ToolException(f'get_array_size() only works on array type symbols!')
    return var.num_indices()

get_array_size_tool = StructuredTool.from_function(
        func=get_array_size,
        handle_tool_error=True
        )

def get_value_string(sym: SymbolInfo) -> str:
    """
    For symbols with type "string" returns the value of the symbol as a string.

    For symbols with type "enum" returns the enum name as a string.

    Args:
        sym: A basic or pointer or enum type symbol.

    Returns:
        The value of the symbol.
    """
    var = debugger.symbols[sym.id]

    # return the value for valid symbol types.
    if var.type() in { SymbolType.STRING, SymbolType.ENUM }:
        return var.value_string()

    raise ToolException(f'Only string and enumerations have a value_string parameter')

get_value_string_tool = StructuredTool.from_function(
        func=get_value_string,
        handle_tool_error=True
        )

def get_value_number(sym: SymbolInfo) -> Union[int, float]:
    """
    For a symbol with type "basic" or "pointer", returns the value of the
    symbol which can either be an integer or a float value. For pointer
    symbols, the value returned is the address held by the pointer symbol.

    For a symbol with type "enum", returns the integer representation of the
    enum as an unsigned int.

    Args:
        sym: A basic or pointer or enum type symbol.

    Returns:
        The value of the symbol.
    """
    var = debugger.symbols[sym.id]

    # return the value for valid symbol types.
    if var.type() in { SymbolType.BASIC, SymbolType.POINTER, SymbolType.ENUM }:
        return var.value_number()

    raise ToolException(f'Only basic/pointer/enum variables have a value. {sym.name} does not have basic value!')

get_value_number_tool = StructuredTool.from_function(
        func=get_value_number,
        handle_tool_error=True
        )

# message for the AI tool.
SYSTEM_MESSAGE = SystemMessage("""
You are an intelligent assistant designed to help users debug their programs. 
Invoke one of the provided tools by interpreting the user command.

When a user requests you to get a global variable, assume C-notation. For
example, if the request is for "var.member1[10].member2", it means get the
global variable "var" as a Symbol using get_global(), and traverse it using the
provided tools (get_member, get_index etc.,) until you reach the desired
Symbol.

""")

def model(state: MessagesState):
    return {"messages": [agent.model.invoke([SYSTEM_MESSAGE] + state["messages"])]}

class LLDBAgent:

    def __init__(self):
        self.memory = MemorySaver()

        # collect the set of tools available.
        self.tools = [
                create_target_from_file, 
                set_breakpoint_from_label,
                launch_process,
                get_global,
                get_member_tool,
                get_members_tool,
                get_array_size_tool,
                get_index_tool,
                get_value_number_tool,
                get_value_string_tool
                ]

        # create a model and bind the tools.
        self.model = ChatOpenAI(temperature=0)

        self.graph = None
        self.react = None
        self.build_react_agent()

        # The thread id is a unique key that identifies
        # this particular conversation.
        # We'll just generate a random uuid here.
        # This enables a single application to manage conversations among multiple users.
        thread_id = uuid.uuid4()
        self.config = { 
                  "configurable": { 
                                   "thread_id": thread_id 
                                   },
                  "recursion_limit": 20
                 }

    def build_graph(self):

        # bind model with tools.
        self.model.bind_tools(self.tools)

        builder = StateGraph(MessagesState)
        
        # add new nodes.
        builder.add_node("model", model)
        builder.add_node("tools", ToolNode(self.tools))

        # connect them.
        builder.add_edge(START, "model")
        # -- if the "model" wants a tool, routes to tool node.
        # -- if the "model" doesn't want a tool, routes to END node automatically.
        builder.add_conditional_edges("model", tools_condition)
        builder.add_edge("tools", "model")

        # compile the graph.
        self.graph = builder.compile(checkpointer=self.memory)

    def build_react_agent(self):

        self.react = create_react_agent(
                model = self.model,
                tools = self.tools,
                checkpointer=self.memory
                )

    def do(self, msg: str):

        if self.graph:
            messages = [HumanMessage(content=msg)]
            messages = self.graph.invoke({"messages": messages}, self.config)
            for m in messages['messages']:
                m.pretty_print()
        elif self.react:
            inputs = {"messages": [("user", msg)]}
            stream = self.react.stream(inputs, stream_mode="values", config=self.config)
            for s in stream:
                message = s["messages"][-1]
                if isinstance(message, tuple):
                    print(message)
                else:
                    message.pretty_print()
        
agent = LLDBAgent()

if __name__ == "__main__":

    # run some initial commands.
    agent.do("Create a new target called example with the executable example")
    agent.do("Set a breakpoint on printf")
    agent.do("Run the program")

    IPython.embed()


