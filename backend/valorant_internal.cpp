/*
 * VALORANT Internal Memory Reader DLL
 * 
 * This DLL gets injected into VALORANT's process and runs INSIDE the game.
 * It can hook game functions and read data structures without hardcoded offsets.
 * 
 * Compilation:
 *   x64 MSVC: cl /LD /O2 valorant_internal.cpp /Fe:valorant_internal.dll
 *   MinGW:    g++ -shared -o valorant_internal.dll valorant_internal.cpp -std=c++17
 * 
 * WARNING: Extremely detectable by Vanguard. Use at your own risk.
 */

#include <windows.h>
#include <string>
#include <vector>
#include <cstdio>

// Shared memory name for IPC with Python
#define SHARED_MEMORY_NAME "VortexValorantPlayerData"
#define SHARED_MEMORY_SIZE 65536

// Player data structure
struct PlayerData {
    wchar_t username[64];
    wchar_t tag[16];
    wchar_t agent[32];
    int level;
    int rank;
};

// Shared memory structure
struct SharedData {
    int player_count;
    PlayerData players[10];
    bool updated;
};

// Global variables
HANDLE g_hSharedMemory = NULL;
SharedData* g_pSharedData = NULL;
HANDLE g_hHookThread = NULL;
bool g_running = true;

// Function signatures (these would be found via pattern scanning)
// Example: UnrealEngine uses specific vtable patterns for actors
typedef void* (__fastcall* GetPlayerArray_t)();
typedef const wchar_t* (__thiscall* GetPlayerName_t)(void* player);

GetPlayerArray_t g_GetPlayerArray = nullptr;
GetPlayerName_t g_GetPlayerName = nullptr;

/**
 * Pattern scanning to find functions
 * This finds functions by their byte signature, no hardcoded offsets!
 */
uintptr_t FindPattern(const char* pattern, const char* mask) {
    MODULEINFO modInfo;
    GetModuleInformation(GetCurrentProcess(), GetModuleHandle(NULL), &modInfo, sizeof(MODULEINFO));
    
    uintptr_t base = (uintptr_t)modInfo.lpBaseOfDll;
    uintptr_t size = modInfo.SizeOfImage;
    
    size_t patternLen = strlen(mask);
    
    for (uintptr_t i = 0; i < size - patternLen; i++) {
        bool found = true;
        for (size_t j = 0; j < patternLen; j++) {
            if (mask[j] != '?' && pattern[j] != *(char*)(base + i + j)) {
                found = false;
                break;
            }
        }
        if (found) {
            return base + i;
        }
    }
    
    return 0;
}

/**
 * Initialize shared memory for IPC with Python
 */
bool InitializeSharedMemory() {
    // Create shared memory
    g_hSharedMemory = CreateFileMappingA(
        INVALID_HANDLE_VALUE,
        NULL,
        PAGE_READWRITE,
        0,
        SHARED_MEMORY_SIZE,
        SHARED_MEMORY_NAME
    );
    
    if (!g_hSharedMemory) {
        return false;
    }
    
    // Map view
    g_pSharedData = (SharedData*)MapViewOfFile(
        g_hSharedMemory,
        FILE_MAP_ALL_ACCESS,
        0,
        0,
        SHARED_MEMORY_SIZE
    );
    
    if (!g_pSharedData) {
        CloseHandle(g_hSharedMemory);
        g_hSharedMemory = NULL;
        return false;
    }
    
    // Initialize
    memset(g_pSharedData, 0, sizeof(SharedData));
    g_pSharedData->updated = false;
    
    return true;
}

/**
 * Find game functions using pattern scanning
 * No hardcoded offsets needed!
 */
bool FindGameFunctions() {
    // Example patterns (these are FAKE - you'd need to find real ones)
    // Real patterns are found using tools like x64dbg, Ghidra, or IDA
    
    // Pattern for GetPlayerArray might look like:
    // 48 8B 05 ?? ?? ?? ?? 48 85 C0 74 ?? 48 8B 00
    const char* playerArrayPattern = "\x48\x8B\x05\x00\x00\x00\x00\x48\x85\xC0";
    const char* playerArrayMask = "xxx????xxx";
    
    uintptr_t addr = FindPattern(playerArrayPattern, playerArrayMask);
    if (addr) {
        // Resolve relative address
        int32_t offset = *(int32_t*)(addr + 3);
        g_GetPlayerArray = (GetPlayerArray_t)(addr + 7 + offset);
    }
    
    // You would repeat this for each function you need to hook
    
    return g_GetPlayerArray != nullptr;
}

/**
 * Hook that runs periodically to read player data
 * This uses the GAME'S OWN FUNCTIONS - no offsets!
 */
DWORD WINAPI PlayerDataUpdateThread(LPVOID lpParam) {
    while (g_running) {
        if (g_GetPlayerArray && g_pSharedData) {
            // Call the game's own function to get players
            void* playerArray = g_GetPlayerArray();
            
            if (playerArray) {
                // Read player data using game's structures
                // The game knows its own structure layout!
                
                // Example pseudo-code (actual implementation depends on game):
                // int count = *(int*)playerArray;
                // void** players = (void**)((char*)playerArray + 8);
                // 
                // g_pSharedData->player_count = min(count, 10);
                // 
                // for (int i = 0; i < g_pSharedData->player_count; i++) {
                //     void* player = players[i];
                //     
                //     // Get username using game's function
                //     const wchar_t* name = g_GetPlayerName(player);
                //     if (name) {
                //         wcscpy_s(g_pSharedData->players[i].username, 64, name);
                //     }
                // }
                
                // Mark as updated
                g_pSharedData->updated = true;
            }
        }
        
        Sleep(1000);  // Update every second
    }
    
    return 0;
}

/**
 * Alternative: Hook DirectX to read from the game's rendering
 * This can read player names as they're being rendered on screen!
 */
typedef long(__stdcall* Present_t)(IDXGISwapChain*, UINT, UINT);
Present_t oPresent = nullptr;

long __stdcall hkPresent(IDXGISwapChain* pSwapChain, UINT SyncInterval, UINT Flags) {
    // When the game renders player names, we can intercept them here
    // This is how many overlays work
    
    // The game's text rendering function is being called with player names
    // We can hook that and capture the strings
    
    return oPresent(pSwapChain, SyncInterval, Flags);
}

/**
 * Initialize hooks
 */
bool InitializeHooks() {
    // Find game functions
    if (!FindGameFunctions()) {
        return false;
    }
    
    // Start player data update thread
    g_hHookThread = CreateThread(
        NULL,
        0,
        PlayerDataUpdateThread,
        NULL,
        0,
        NULL
    );
    
    return g_hHookThread != NULL;
}

/**
 * Cleanup
 */
void Cleanup() {
    g_running = false;
    
    if (g_hHookThread) {
        WaitForSingleObject(g_hHookThread, 5000);
        CloseHandle(g_hHookThread);
    }
    
    if (g_pSharedData) {
        UnmapViewOfFile(g_pSharedData);
    }
    
    if (g_hSharedMemory) {
        CloseHandle(g_hSharedMemory);
    }
}

/**
 * DLL Entry Point
 * Called when DLL is injected
 */
BOOL APIENTRY DllMain(HMODULE hModule, DWORD dwReason, LPVOID lpReserved) {
    switch (dwReason) {
        case DLL_PROCESS_ATTACH:
            // DLL just got injected!
            DisableThreadLibraryCalls(hModule);
            
            // Initialize shared memory for IPC
            if (!InitializeSharedMemory()) {
                return FALSE;
            }
            
            // Initialize hooks
            if (!InitializeHooks()) {
                Cleanup();
                return FALSE;
            }
            
            // Write status to shared memory
            if (g_pSharedData) {
                wcscpy_s(g_pSharedData->players[0].username, 64, L"INTERNAL_DLL_LOADED");
            }
            
            break;
            
        case DLL_PROCESS_DETACH:
            // DLL is being unloaded
            Cleanup();
            break;
    }
    
    return TRUE;
}

/*
 * HOW THIS WORKS WITHOUT OFFSETS:
 * 
 * 1. PATTERN SCANNING
 *    - Instead of hardcoded offsets, we scan for unique byte patterns
 *    - These patterns are the actual compiled assembly code
 *    - Example: "48 8B 05 ?? ?? ?? ??" is MOV RAX, [RIP+offset]
 *    - We find the pattern and follow the address
 * 
 * 2. VTABLE HOOKING
 *    - Game objects have virtual function tables
 *    - We can hook these to intercept function calls
 *    - When game calls GetPlayerName(), our hook runs first
 * 
 * 3. USING GAME'S OWN CODE
 *    - We call the game's functions directly
 *    - The game knows its own structure layouts
 *    - No need to hardcode struct offsets
 * 
 * 4. HOOKING RENDERING
 *    - Hook DirectX Present() or text rendering
 *    - Capture player names as they're drawn on screen
 *    - Works even if structures change
 * 
 * WHY NO OFFSET UPDATES NEEDED:
 * - Patterns are based on compiled code structure
 *    - Unless the entire function is rewritten, pattern stays same
 * - We use the game's own functions
 * - We intercept data "in flight" not from static memory
 * 
 * TRADEOFFS:
 * + No offset updates needed
 * + More robust against patches
 * - Much more detectable (code runs inside game)
 * - Vanguard will likely catch this immediately
 * - Requires C++ compilation for each update
 */
