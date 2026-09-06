"""
DLL Injection Module for Internal Memory Reading

This module injects a custom DLL into the VALORANT process, allowing code to run
INSIDE the game's memory space. This enables:
- Direct access to game functions and structures
- Function hooking without hardcoded offsets
- Automatic offset resolution using game's own code

WARNING: DLL injection is highly detectable by anti-cheat systems like Vanguard.
This is significantly riskier than external memory reading.
"""

import ctypes
import ctypes.wintypes
import os
from typing import Optional, Dict, Any

# Windows API constants
PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04
PAGE_EXECUTE_READWRITE = 0x40

# Kernel32 functions
kernel32 = ctypes.windll.kernel32
kernel32.VirtualAllocEx.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.DWORD
]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p

kernel32.WriteProcessMemory.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t)
]
kernel32.WriteProcessMemory.restype = ctypes.wintypes.BOOL

kernel32.CreateRemoteThread.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.wintypes.DWORD,
    ctypes.POINTER(ctypes.wintypes.DWORD)
]
kernel32.CreateRemoteThread.restype = ctypes.wintypes.HANDLE


class DLLInjector:
    """
    Injects a DLL into a target process using the LoadLibrary technique.
    
    This is the most common injection method:
    1. Allocate memory in target process
    2. Write DLL path to that memory
    3. Create remote thread that calls LoadLibrary with the DLL path
    4. The game loads our DLL and runs our code inside its process
    """
    
    def __init__(self):
        self.process_handle = None
        self.process_id = None
        self.injected_dll_path = None
        
    def inject_dll(self, process_id: int, dll_path: str) -> Dict[str, Any]:
        """
        Inject a DLL into the target process.
        
        Args:
            process_id: Target process ID
            dll_path: Full path to the DLL to inject
            
        Returns:
            Dict with success status and message
        """
        # Validate DLL exists
        if not os.path.exists(dll_path):
            return {
                "success": False,
                "message": f"DLL not found: {dll_path}"
            }
        
        # Convert to absolute path
        dll_path = os.path.abspath(dll_path)
        
        try:
            # Step 1: Open target process with full access
            self.process_handle = kernel32.OpenProcess(
                PROCESS_ALL_ACCESS,
                False,
                process_id
            )
            
            if not self.process_handle:
                return {
                    "success": False,
                    "message": "Failed to open process. Try running as administrator."
                }
            
            self.process_id = process_id
            
            # Step 2: Get address of LoadLibraryA in kernel32.dll
            # LoadLibraryA exists in every process at the same address (ASLR aware)
            loadlibrary_addr = kernel32.GetProcAddress(
                kernel32.GetModuleHandleA(b"kernel32.dll"),
                b"LoadLibraryA"
            )
            
            if not loadlibrary_addr:
                self._cleanup()
                return {
                    "success": False,
                    "message": "Failed to get LoadLibraryA address"
                }
            
            # Step 3: Allocate memory in target process for DLL path
            dll_path_bytes = dll_path.encode('utf-8') + b'\x00'
            path_size = len(dll_path_bytes)
            
            remote_memory = kernel32.VirtualAllocEx(
                self.process_handle,
                None,
                path_size,
                MEM_COMMIT | MEM_RESERVE,
                PAGE_READWRITE
            )
            
            if not remote_memory:
                self._cleanup()
                return {
                    "success": False,
                    "message": "Failed to allocate memory in target process"
                }
            
            # Step 4: Write DLL path to allocated memory
            bytes_written = ctypes.c_size_t(0)
            write_success = kernel32.WriteProcessMemory(
                self.process_handle,
                remote_memory,
                dll_path_bytes,
                path_size,
                ctypes.byref(bytes_written)
            )
            
            if not write_success or bytes_written.value != path_size:
                kernel32.VirtualFreeEx(self.process_handle, remote_memory, 0, MEM_RELEASE)
                self._cleanup()
                return {
                    "success": False,
                    "message": "Failed to write DLL path to target process"
                }
            
            # Step 5: Create remote thread that calls LoadLibraryA with our DLL path
            thread_id = ctypes.wintypes.DWORD(0)
            thread_handle = kernel32.CreateRemoteThread(
                self.process_handle,
                None,
                0,
                loadlibrary_addr,
                remote_memory,
                0,
                ctypes.byref(thread_id)
            )
            
            if not thread_handle:
                kernel32.VirtualFreeEx(self.process_handle, remote_memory, 0, MEM_RELEASE)
                self._cleanup()
                return {
                    "success": False,
                    "message": "Failed to create remote thread. Vanguard may have blocked it."
                }
            
            # Wait for the thread to complete (DLL loading)
            kernel32.WaitForSingleObject(thread_handle, 5000)  # 5 second timeout
            
            # Get the thread exit code (LoadLibrary return value = module handle)
            exit_code = ctypes.wintypes.DWORD(0)
            kernel32.GetExitCodeThread(thread_handle, ctypes.byref(exit_code))
            
            # Cleanup
            kernel32.CloseHandle(thread_handle)
            kernel32.VirtualFreeEx(self.process_handle, remote_memory, 0, MEM_RELEASE)
            
            if exit_code.value == 0:
                self._cleanup()
                return {
                    "success": False,
                    "message": "DLL loaded but LoadLibrary returned NULL. Check DLL dependencies."
                }
            
            self.injected_dll_path = dll_path
            
            return {
                "success": True,
                "message": "DLL injected successfully",
                "module_handle": exit_code.value,
                "thread_id": thread_id.value
            }
            
        except Exception as e:
            self._cleanup()
            return {
                "success": False,
                "message": f"Injection error: {str(e)}"
            }
    
    def _cleanup(self):
        """Clean up process handle"""
        if self.process_handle:
            kernel32.CloseHandle(self.process_handle)
            self.process_handle = None
        self.process_id = None


class InternalMemoryReader:
    """
    Manages internal memory reading via injected DLL.
    
    The injected DLL runs inside VALORANT and can:
    - Hook game functions
    - Read game structures directly
    - Use the game's own code to find player data
    - No offsets needed!
    """
    
    def __init__(self):
        self.injector = DLLInjector()
        self.injected = False
        self.dll_path = None
        
    def build_injection_dll(self) -> str:
        """
        Build or locate the injection DLL.
        
        In a real implementation, this would:
        1. Compile valorant_hook.dll from C++ source
        2. Include game hooks for player data
        3. Export functions to communicate with Python
        
        Returns:
            Path to the DLL
        """
        # Check for pre-built DLL
        dll_path = os.path.join(
            os.path.dirname(__file__),
            "valorant_internal.dll"
        )
        
        if os.path.exists(dll_path):
            return dll_path
        
        # DLL not found - need to build it
        return None
    
    def inject(self, process_id: int) -> Dict[str, Any]:
        """
        Inject the internal DLL into VALORANT.
        
        Args:
            process_id: VALORANT process ID
            
        Returns:
            Dict with success status
        """
        # Get DLL path
        self.dll_path = self.build_injection_dll()
        
        if not self.dll_path:
            return {
                "success": False,
                "message": "Internal DLL not found. You need to compile valorant_internal.dll first."
            }
        
        # Perform injection
        result = self.injector.inject_dll(process_id, self.dll_path)
        
        if result["success"]:
            self.injected = True
        
        return result
    
    def is_injected(self) -> bool:
        """Check if DLL is currently injected"""
        return self.injected
    
    def get_players(self) -> Dict[str, Any]:
        """
        Get player data from the injected DLL.
        
        The injected DLL would expose this via:
        - Shared memory
        - Named pipes
        - Window messages
        - Export functions
        
        Returns:
            Dict with player list
        """
        if not self.injected:
            return {
                "success": False,
                "message": "DLL not injected",
                "players": []
            }
        
        # TODO: Implement IPC with injected DLL
        # The DLL running inside VALORANT would write player data to
        # shared memory or a pipe that we read here
        
        return {
            "success": True,
            "players": [],
            "message": "DLL injected but IPC not implemented yet"
        }


# Global instance
_internal_reader = InternalMemoryReader()


def inject_internal_dll(process_id: int) -> Dict[str, Any]:
    """Inject internal memory reading DLL"""
    return _internal_reader.inject(process_id)


def is_internal_injected() -> bool:
    """Check if internal DLL is injected"""
    return _internal_reader.is_injected()


def get_internal_players() -> Dict[str, Any]:
    """Get players from internal DLL"""
    return _internal_reader.get_players()
