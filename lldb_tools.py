from lldb_wrapper import LLDBWrapper
from langchain_core.tools import tool

lldb_wrapper = LLDBWrapper()

@tool
def create_target(file_path: str) -> str:
    """
    Create a debugging target for the specified file.
    """
    target = lldb_wrapper.create_target(file_path)
    return f"Created target for {file_path}"

@tool
def set_breakpoint(file_path: str, line_number: int) -> str:
    """
    Set a breakpoint at the specified file and line number.
    """
    bp = lldb_wrapper.set_breakpoint(file_path, line_number)
    return f"Set breakpoint at {file_path}:{line_number}"

@tool
def launch_process() -> str:
    """
    Launch the process for debugging.
    """
    process = lldb_wrapper.launch_process()
    return "Process launched."

@tool
def get_backtrace() -> str:
    """
    Get the backtrace of the current thread.
    """
    return lldb_wrapper.get_backtrace()

