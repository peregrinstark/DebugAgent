import sys
import logging

import IPython

from lldb_wrapper import LLDB
from debugger_api import ProcessState, Symbol, SymbolType, SymbolNotFound
from typing import List, Tuple, Literal, Any, Dict, Union, Optional
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool, StructuredTool, ToolException
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import create_react_agent
import uuid

HIERARCHY_REQUEST = """
If the user requests a variable of the form
"var.member1.member2[<idx>].member3", where <idx> is a number, parse it using a
C-variable notation and get the value by traversing recursively as follows
(using the above example):

1. v = get_global(target, "var2")
2. v = get_member(target, v, "member1")
3. v = get_member(target, v, "member2")
3. v = get_index(target, v, <idx>)
    - You can optionally check if the <idx> is in range by comparing it with
      the value returned by get_array_size(target, v)
4. v = get_member(target, v, "member3")

Allow wildcards for <idx>. For example, if the user uses "*" for index, apply
the request for all elements of the corresponding array (whose size is
determined using get_array_size).

You can also allow ranges (ex: 1-10)for <idx>. In that case, you should
retrieve the array indices corresponding to the user provided range.

"""

# message for the AI tool.
SYSTEM_MESSAGE = SystemMessage(
f"""
You are an intelligent assistant designed to help users debug their programs.
As a debugger you have access to a collection of targets indexed by name that
can be retrieved using the get_target() tool. 

Each target has a collection of variables (also called Symbols) that can be
retrieved on user request via the get_global() tool. Note that the get_global
only takes a C style identifier as an input.

Each variable (also known as a "Symbol") can be thought of as a C style
variable that can either be one of:

- Structures
- Unions
- Arrays
- Enums
- Strings (char arrays or const char *)
- Basic Types (such as integers and floating point values).

Each symbol has a type entry that indicates one of the above types. Structures,
Unions and Arrays are "aggregate" types that inturn contains collections of
symbols while the rest are "scalar" types whose values can be retrieved using
get_value_string() or get_value_number() as described below>

Each symbol can be traversed using the following tools. The following functions
work only on aggregate types (Structures, Unions, Arrays).

- get_member() returns a symbol that represents the member of a structure
  variable. Obviously, this only works for structure variables.
- get_members() returns all the members of a structure variable.
- get_array_size() returns the size of an array variable.
- get_index() returs a symbol at the specified index of an array variable.

These functions work only on "scalar" types (Strings, Enums, Basic types):

- get_value_number() returns the value as an integer or floating point number
  for a basic integer or floating point symbol. It also returns the integer
  value of a enum variable.
- get_value_string() returns the value of a string Symbol type (char arrays or
  const char *). It also returns the name of a enum symbol.

When the user requests a value, use get_value_number of get_value_string to
retrieve the value for "Scalar" types, but tell the user that you cannot
retrieve a value for "Aggregate" types.

Only call functions that are appropriate to be called. For example,
get_members() is only appropriate if the corresponding Symbol is a structure
type. Do not call get_value_*() functions on aggregate types.

{HIERARCHY_REQUEST}

If the user requests to print an aggregate type, try to traverse the aggregate
type by invoking get_member(), get_index() etc., and print it C-sytel structure
notation.

""")
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

    def get_symbol(self, info: SymbolInfo):
        return self.symbols.get(info.id)

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

def get_global(target: TargetInfo, name: str) -> SymbolInfo:
    """
    Returns a global variable read from the target. A variable is a Symbol with
    a type defined by SymbolType.

    Args:
        target: Name of the target to read variable from.
        name: Name of the global variable to fetch. Should be a C-style
        identifier without any special case characters.

    Returns:
        A Symbol
    """
    # check if the name contains special characters.
    spl_chars = any(name.find(c) > 0 for c in '[].')
    if spl_chars:
        raise ToolException(f"""
The provided name argument must not contain special
characters. If the user passed a C-style string, parse and
handle it recursively. {HIERARCHY_REQUEST}.
                """)

    # get the target.
    _target = debugger.lldb.target(target.name)
    try:
        # get the variable from the target.
        var = _target.get_global(name)
    except SymbolNotFound:
        raise ToolException(f"""
A symbol with the specified name {name} was not found. Can you please
check if you are parsing the user request correctly? {HIERARCHY_REQUEST}
        """)
    # append this object with a unique UUID to our application database.
    return debugger.add_symbol(var)

get_global_tool = StructuredTool.from_function(
        func=get_global,
        handle_tool_error=True
        )

@tool(parse_docstring=True)
def get_targets() -> List[TargetInfo]:
    """
    Gets all targets available in the debugger.

    Returns:
        List of all targets available in the debugger.
    """
    targets = []
    for name, _ in debugger.lldb.targets().items():
        targets.append(TargetInfo(name=name))
    return targets

ERR_REROUTE_STR = {
        SymbolType.ARRAY: 'Use get_index(...) or get_array_size(...) instead since it of type array',
        SymbolType.BASIC: 'Use get_value_number(...) instead since it of type basic',
        SymbolType.ENUM: 'Use get_value_string(...) instead since it of type enum',
        SymbolType.STRING: 'Use get_value_string(...) instead since it of type string',
        SymbolType.STRUCT: 'Use get_member(...) instead since it of type string',
}

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
    var = debugger.get_symbol(sym)
    if var is None:
        raise ToolException(f"""
        The symbol with this id {sym.id} is not found!
        """)
    if var.name() != sym.name:
        raise ToolException(f"""
        The name of the symbol {sym.name} passed does not match its id {sym.id}!
        """)
    if var.type() != SymbolType.STRUCT:
        raise ToolException(f"""
        {sym.name} is of type {var.type()} and does not have members. {ERR_REROUTE_STR[var.type()]}.
        """)
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
        raise ToolException(f"""
        {sym.name} is of type {var.type()} and does not have members. {ERR_REROUTE_STR[var.type()]}.
        """)
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
        raise ToolException(f"""
        {sym.name} is not an array. {ERR_REROUTE_STR[var.type()]}.
        """)
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
        raise ToolException(f"""
        {sym.name} is not array. {ERR_REROUTE_STR[var.type()]}.
        """)
    return var.num_indices()

get_array_size_tool = StructuredTool.from_function(
        func=get_array_size,
        handle_tool_error=True
        )

def get_value_string(sym: SymbolInfo) -> Optional[str]:
    """
    For symbols with type "string" returns the value of the symbol as a string.
    It could potentially be an empty string. Do not hallucinate and try to
    coerce it with a valid string.

    For symbols with type "enum" returns the enum name as a string.

    Args:
        sym: A basic or pointer or enum type symbol.

    Returns:
        The value of the symbol as a string. It could potentially be empty.
        Indicate it accordingly if so.
    """
    var = debugger.symbols[sym.id]

    # return the value for valid symbol types.
    if var.type() in { SymbolType.STRING, SymbolType.ENUM }:
        out = var.value_string()
        if len(out) == 0:
            return None 
        else:
            return out

    raise ToolException(f"""
    get_value_string() only works on String and Enum types, but
    {sym.name} is of type {var.type()}! {ERR_REROUTE_STR[var.type()]}.
    """)

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

    raise ToolException(f"""
    get_value_number() only works on Basic, Pointer and Enum types, but
    {sym.name} is of type {var.type()}!
    """)

get_value_number_tool = StructuredTool.from_function(
        func=get_value_number,
        handle_tool_error=True
        )


def model(state: MessagesState):
    return {"messages": [agent.model.invoke([SYSTEM_MESSAGE] + state["messages"])]}

class LLDBAgent:

    def __init__(self):
        self.memory = MemorySaver()

        # collect the set of tools available.
        self.tools = [
                # create_target_from_file, 
                # set_breakpoint_from_label,
                # launch_process,
                get_targets,
                get_global_tool,
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
                  "max_concurrency": 1,
                  "recursion_limit": 30,
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
                prompt = SYSTEM_MESSAGE,
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
            msg_count = 0
            for s in stream:
                for count in range(msg_count, len(s['messages'])):
                    message = s['messages'][count]
                    # if message.type == 'tool':
                    #    import pdb; pdb.set_trace()
                    if isinstance(message, tuple):
                        print(message)
                    else:
                        message.pretty_print()
                msg_count = len(s['messages'])

if __name__ == "__main__":

    # prepare the target.
    target = debugger.lldb.create_target_from_file("example", "example")
    target.set_breakpoint_by_label('printf')
    status = target.launch_process()
    print(f'Target stopped at {repr(status)}')

    # create the agent.
    agent = LLDBAgent()
    IPython.embed()
