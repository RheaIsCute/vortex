"""
Memory Reader Module for VALORANT
Provides direct process memory reading to access hidden player information.

WARNING: This module uses ReadProcessMemory and similar low-level Windows APIs
to read game memory. This may violate Riot Games' Terms of Service and could
result in account bans or penalties. Use at your own risk.

This is disabled by default and requires explicit user opt-in.
"""

import ctypes
import ctypes.wintypes
import struct
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

# Windows API constants
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008

# Windows API structures
class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]

class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("GlblcntUsage", ctypes.wintypes.DWORD),
        ("ProccntUsage", ctypes.wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", ctypes.wintypes.DWORD),
        ("hModule", ctypes.wintypes.HMODULE),
        ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260),
    ]

@dataclass
class PlayerInfo:
    """Information about a player extracted from game memory"""
    username: str
    tag: str
    agent: Optional[str] = None
    level: Optional[int] = None
    rank: Optional[str] = None


class ValorantMemoryReader:
    """
    Reads VALORANT process memory to extract player information.
    
    This class provides low-level memory access to the VALORANT game process
    to read player data that may not be accessible through official APIs.
    """
    
    def __init__(self):
        self.kernel32 = ctypes.windll.kernel32
        self.process_handle = None
        self.process_id = None
        self.base_address = None
        
    def find_valorant_process(self) -> Optional[int]:
        """
        Find the VALORANT process ID.
        
        Returns:
            Process ID if found, None otherwise
        """
        snapshot = self.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == -1:
            return None
        
        try:
            pe32 = PROCESSENTRY32()
            pe32.dwSize = ctypes.sizeof(PROCESSENTRY32)
            
            if not self.kernel32.Process32First(snapshot, ctypes.byref(pe32)):
                return None
            
            while True:
                process_name = pe32.szExeFile.decode('utf-8', errors='ignore').lower()
                # VALORANT's main process names
                if process_name in ['valorant.exe', 'valorant-win64-shipping.exe']:
                    return pe32.th32ProcessID
                
                if not self.kernel32.Process32Next(snapshot, ctypes.byref(pe32)):
                    break
                    
        finally:
            self.kernel32.CloseHandle(snapshot)
        
        return None
    
    def open_process(self, process_id: int) -> bool:
        """
        Open a handle to the VALORANT process with read permissions.
        
        Args:
            process_id: The process ID to open
            
        Returns:
            True if successful, False otherwise
        """
        self.process_id = process_id
        self.process_handle = self.kernel32.OpenProcess(
            PROCESS_VM_READ | PROCESS_QUERY_INFORMATION,
            False,
            process_id
        )
        
        if not self.process_handle:
            return False
        
        # Find the base module address
        self.base_address = self._get_module_base_address(process_id)
        return self.base_address is not None
    
    def _get_module_base_address(self, process_id: int) -> Optional[int]:
        """Get the base address of the main VALORANT module"""
        snapshot = self.kernel32.CreateToolhelp32Snapshot(
            TH32CS_SNAPMODULE, 
            process_id
        )
        
        if snapshot == -1:
            return None
        
        try:
            me32 = MODULEENTRY32()
            me32.dwSize = ctypes.sizeof(MODULEENTRY32)
            
            if not self.kernel32.Module32First(snapshot, ctypes.byref(me32)):
                return None
            
            # The first module is typically the main executable
            return ctypes.cast(me32.modBaseAddr, ctypes.c_void_p).value
            
        finally:
            self.kernel32.CloseHandle(snapshot)
    
    def read_memory(self, address: int, size: int) -> Optional[bytes]:
        """
        Read memory from the VALORANT process.
        
        Args:
            address: Memory address to read from
            size: Number of bytes to read
            
        Returns:
            Bytes read, or None if failed
        """
        if not self.process_handle:
            return None
        
        buffer = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t(0)
        
        success = self.kernel32.ReadProcessMemory(
            self.process_handle,
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(bytes_read)
        )
        
        if not success or bytes_read.value != size:
            return None
        
        return buffer.raw
    
    def read_string(self, address: int, max_length: int = 256) -> Optional[str]:
        """
        Read a null-terminated string from memory.
        
        Args:
            address: Memory address to read from
            max_length: Maximum string length to read
            
        Returns:
            String if found, None otherwise
        """
        data = self.read_memory(address, max_length)
        if not data:
            return None
        
        try:
            # Try UTF-8 decoding first (most common)
            null_pos = data.find(b'\x00')
            if null_pos != -1:
                return data[:null_pos].decode('utf-8', errors='ignore')
            return data.decode('utf-8', errors='ignore')
        except:
            return None
    
    def scan_memory_regions(self) -> List[tuple]:
        """
        Get all readable memory regions of the process.
        
        Returns:
            List of (base_address, size) tuples
        """
        if not self.process_handle:
            return []
        
        regions = []
        address = 0
        
        # MEMORY_BASIC_INFORMATION structure
        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", ctypes.wintypes.DWORD),
                ("RegionSize", ctypes.c_size_t),
                ("State", ctypes.wintypes.DWORD),
                ("Protect", ctypes.wintypes.DWORD),
                ("Type", ctypes.wintypes.DWORD),
            ]
        
        # Memory protection constants
        PAGE_READONLY = 0x02
        PAGE_READWRITE = 0x04
        PAGE_WRITECOPY = 0x08
        PAGE_EXECUTE_READ = 0x20
        PAGE_EXECUTE_READWRITE = 0x40
        PAGE_GUARD = 0x100
        PAGE_NOCACHE = 0x200
        MEM_COMMIT = 0x1000
        
        # Scan all memory regions
        while address < 0x7FFFFFFFFFFF:  # Max user-mode address on x64
            mbi = MEMORY_BASIC_INFORMATION()
            result = self.kernel32.VirtualQueryEx(
                self.process_handle,
                ctypes.c_void_p(address),
                ctypes.byref(mbi),
                ctypes.sizeof(mbi)
            )
            
            if result == 0:
                break
            
            # Check if region is committed and readable
            if (mbi.State == MEM_COMMIT and 
                mbi.Protect in [PAGE_READONLY, PAGE_READWRITE, PAGE_WRITECOPY,
                               PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE] and
                not (mbi.Protect & PAGE_GUARD) and
                not (mbi.Protect & PAGE_NOCACHE)):
                regions.append((mbi.BaseAddress, mbi.RegionSize))
            
            address += mbi.RegionSize
        
        return regions
    
    def find_pattern(self, pattern: bytes, mask: str = None) -> Optional[int]:
        """
        Search for a byte pattern in process memory.
        
        Args:
            pattern: Byte pattern to search for
            mask: Optional mask (e.g., "xxx??xxx" where ? is wildcard)
            
        Returns:
            Address if found, None otherwise
        """
        regions = self.scan_memory_regions()
        
        for base_addr, size in regions:
            # Limit scan to reasonable region sizes (avoid huge mapped files)
            if size > 100 * 1024 * 1024:  # Skip regions > 100MB
                continue
            
            data = self.read_memory(base_addr, size)
            if not data:
                continue
            
            # Simple pattern matching
            if mask:
                # With mask (? = wildcard)
                for i in range(len(data) - len(pattern)):
                    match = True
                    for j in range(len(pattern)):
                        if mask[j] != '?' and data[i + j] != pattern[j]:
                            match = False
                            break
                    if match:
                        return base_addr + i
            else:
                # Exact pattern match
                index = data.find(pattern)
                if index != -1:
                    return base_addr + index
        
        return None
    
    def find_string_references(self, search_string: str, max_results: int = 100) -> List[int]:
        """
        Find all memory addresses that contain a specific string.
        This can find player names without knowing offsets!
        
        Args:
            search_string: String to search for (e.g., "PlayerName#TAG")
            max_results: Maximum number of results to return
            
        Returns:
            List of memory addresses where the string was found
        """
        results = []
        regions = self.scan_memory_regions()
        
        # Convert string to bytes (try both UTF-8 and UTF-16)
        patterns = [
            search_string.encode('utf-8'),
            search_string.encode('utf-16-le')
        ]
        
        for base_addr, size in regions:
            if size > 50 * 1024 * 1024 or len(results) >= max_results:
                continue
            
            data = self.read_memory(base_addr, size)
            if not data:
                continue
            
            # Search for each encoding
            for pattern in patterns:
                offset = 0
                while offset < len(data) - len(pattern):
                    index = data.find(pattern, offset)
                    if index == -1:
                        break
                    
                    results.append(base_addr + index)
                    offset = index + len(pattern)
                    
                    if len(results) >= max_results:
                        return results
        
        return results
    
    def get_player_list(self) -> List[PlayerInfo]:
        """
        Extract player information from game memory.
        
        This method attempts to find and read the player list structure
        in VALORANT's memory. The exact offsets and patterns would need
        to be reverse engineered and updated with each game patch.
        
        Returns:
            List of PlayerInfo objects
            
        Note:
            Memory offsets change with every VALORANT update. This is a
            skeleton implementation that would need game-specific offsets.
        """
        if not self.process_handle or not self.base_address:
            return []
        
        players = []
        
        # PLACEHOLDER: Real implementation would need:
        # 1. Pattern scanning to find player list array
        # 2. Offsets for username, tag, agent, etc. (changes every patch)
        # 3. Pointer chain traversal to find player structures
        # 4. Proper string reading for Unicode names
        
        # Example pseudo-code structure (WILL NOT WORK without real offsets):
        # player_list_offset = 0xXXXXXXX  # Changes every patch
        # player_list_address = self.base_address + player_list_offset
        # 
        # for i in range(10):  # Max 10 players in a match
        #     player_ptr = self.read_memory(player_list_address + i * 8, 8)
        #     if player_ptr:
        #         player_addr = struct.unpack('<Q', player_ptr)[0]
        #         username = self.read_string(player_addr + username_offset)
        #         tag = self.read_string(player_addr + tag_offset)
        #         if username:
        #             players.append(PlayerInfo(username=username, tag=tag))
        
        return players
    
    def close(self):
        """Close the process handle"""
        if self.process_handle:
            self.kernel32.CloseHandle(self.process_handle)
            self.process_handle = None
            self.process_id = None
            self.base_address = None


class MemoryReaderManager:
    """
    High-level manager for memory reading operations.
    Handles initialization, error handling, and safe shutdown.
    
    Supports two modes:
    - External: ReadProcessMemory (needs offsets, less detectable)
    - Internal: DLL injection (no offsets, highly detectable)
    """
    
    def __init__(self):
        self.reader = None
        self.enabled = False
        self.mode = "external"  # "external" or "internal"
        self.internal_shared_memory = None
        
    def enable(self, mode: str = "external") -> Dict[str, Any]:
        """
        Enable memory reading and attach to VALORANT process.
        
        Args:
            mode: "external" (ReadProcessMemory) or "internal" (DLL injection)
        
        Returns:
            Dict with success status and message
        """
        self.mode = mode
        
        if mode == "internal":
            return self._enable_internal()
        else:
            return self._enable_external()
    
    def _enable_external(self) -> Dict[str, Any]:
        """Enable external memory reading (ReadProcessMemory)"""
        try:
            self.reader = ValorantMemoryReader()
            
            # Find VALORANT process
            pid = self.reader.find_valorant_process()
            if not pid:
                return {
                    "success": False,
                    "message": "VALORANT process not found. Please start the game first."
                }
            
            # Open process
            if not self.reader.open_process(pid):
                return {
                    "success": False,
                    "message": "Failed to open VALORANT process. Try running Vortex as administrator."
                }
            
            self.enabled = True
            return {
                "success": True,
                "message": "External memory reading enabled successfully",
                "mode": "external",
                "process_id": pid
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error enabling external memory reading: {str(e)}"
            }
    
    def _enable_internal(self) -> Dict[str, Any]:
        """Enable internal memory reading (DLL injection)"""
        try:
            from backend import injector
            
            # Find VALORANT process
            reader = ValorantMemoryReader()
            pid = reader.find_valorant_process()
            reader.close()
            
            if not pid:
                return {
                    "success": False,
                    "message": "VALORANT process not found. Please start the game first."
                }
            
            # Inject DLL
            result = injector.inject_internal_dll(pid)
            
            if not result["success"]:
                return result
            
            # Open shared memory for IPC
            self._open_shared_memory()
            
            self.enabled = True
            return {
                "success": True,
                "message": "Internal DLL injected successfully (WARNING: Highly detectable!)",
                "mode": "internal",
                "process_id": pid,
                **result
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error enabling internal memory reading: {str(e)}"
            }
    
    def _open_shared_memory(self):
        """Open shared memory for IPC with injected DLL"""
        try:
            # Open existing shared memory created by the DLL
            self.internal_shared_memory = ctypes.windll.kernel32.OpenFileMappingA(
                0x0004,  # FILE_MAP_READ
                False,
                b"VortexValorantPlayerData"
            )
            
            if self.internal_shared_memory:
                # Map view
                self.internal_data_ptr = ctypes.windll.kernel32.MapViewOfFile(
                    self.internal_shared_memory,
                    0x0004,  # FILE_MAP_READ
                    0, 0, 65536
                )
        except:
            pass
    
    def disable(self):
        """Disable memory reading and clean up resources"""
        if self.reader:
            self.reader.close()
            self.reader = None
        
        if self.internal_shared_memory:
            if hasattr(self, 'internal_data_ptr') and self.internal_data_ptr:
                ctypes.windll.kernel32.UnmapViewOfFile(self.internal_data_ptr)
            ctypes.windll.kernel32.CloseHandle(self.internal_shared_memory)
            self.internal_shared_memory = None
        
        self.enabled = False
    
    def get_players(self) -> Dict[str, Any]:
        """
        Get current player list from memory.
        
        Returns:
            Dict with player list or error
        """
        if not self.enabled:
            return {
                "success": False,
                "message": "Memory reading not enabled",
                "players": []
            }
        
        try:
            if self.mode == "internal":
                return self._get_players_internal()
            else:
                return self._get_players_external()
        except Exception as e:
            return {
                "success": False,
                "message": f"Error reading player data: {str(e)}",
                "players": []
            }
    
    def _get_players_external(self) -> Dict[str, Any]:
        """Get players using external memory reading"""
        players = self.reader.get_player_list()
        return {
            "success": True,
            "mode": "external",
            "players": [
                {
                    "username": p.username,
                    "tag": p.tag,
                    "agent": p.agent,
                    "level": p.level,
                    "rank": p.rank
                }
                for p in players
            ]
        }
    
    def _get_players_internal(self) -> Dict[str, Any]:
        """Get players from injected DLL via shared memory"""
        if not self.internal_shared_memory or not hasattr(self, 'internal_data_ptr'):
            return {
                "success": False,
                "message": "Internal shared memory not available",
                "players": []
            }
        
        try:
            # Read from shared memory
            # Structure: int player_count, then PlayerData[10]
            player_count = ctypes.c_int.from_address(self.internal_data_ptr).value
            
            players = []
            # Each PlayerData is: wchar_t username[64], tag[16], agent[32], int level, int rank
            # Total size per player: (64+16+32)*2 + 4 + 4 = 232 bytes
            
            base = self.internal_data_ptr + 4  # Skip player_count
            for i in range(min(player_count, 10)):
                offset = base + (i * 232)
                
                # Read unicode strings
                username = ctypes.wstring_at(offset)
                tag = ctypes.wstring_at(offset + 128)
                agent = ctypes.wstring_at(offset + 160)
                level = ctypes.c_int.from_address(offset + 224).value
                rank = ctypes.c_int.from_address(offset + 228).value
                
                if username:
                    players.append({
                        "username": username,
                        "tag": tag,
                        "agent": agent,
                        "level": level,
                        "rank": rank
                    })
            
            return {
                "success": True,
                "mode": "internal",
                "players": players
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error reading shared memory: {str(e)}",
                "players": []
            }


# Global instance
_memory_manager = MemoryReaderManager()


def is_memory_reading_enabled() -> bool:
    """Check if memory reading is currently enabled"""
    return _memory_manager.enabled


def enable_memory_reading(mode: str = "external") -> Dict[str, Any]:
    """
    Enable memory reading
    
    Args:
        mode: "external" or "internal"
    """
    return _memory_manager.enable(mode)


def disable_memory_reading():
    """Disable memory reading"""
    _memory_manager.disable()


def get_memory_players() -> Dict[str, Any]:
    """Get player list from memory"""
    return _memory_manager.get_players()
