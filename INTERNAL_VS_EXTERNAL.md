# Internal vs External Memory Reading

## Overview

There are two fundamentally different approaches to reading game memory:

### External Memory Reading
- **How it works:** Separate process uses `ReadProcessMemory` API
- **Offset updates:** Required after every patch ❌
- **Detection risk:** Medium 🟡
- **Implementation:** Already implemented in `memory_reader.py`

### Internal Memory Reading (DLL Injection)
- **How it works:** Inject DLL into game, run code inside the process
- **Offset updates:** NOT required ✅
- **Detection risk:** EXTREMELY HIGH 🔴
- **Implementation:** Implemented in `injector.py` + `valorant_internal.cpp`

---

## Why Internal Doesn't Need Offsets

### The Problem with External
External tools must hardcode memory addresses:
```python
# These change EVERY patch:
PLAYER_LIST_OFFSET = 0x12AB5678
USERNAME_OFFSET = 0x80
TAG_OFFSET = 0x90
```

When VALORANT updates, these break and you need to:
1. Open the game in a debugger
2. Find the new addresses
3. Update your code
4. Repeat weekly/bi-weekly

### How Internal Avoids This

**1. Pattern Scanning**
Instead of hardcoded addresses, scan for unique byte patterns:
```cpp
// Find this pattern in compiled code:
// MOV RAX, [RIP+offset]
// Pattern: 48 8B 05 ?? ?? ?? ??
const char* pattern = "\x48\x8B\x05\x00\x00\x00\x00";
const char* mask =    "xxx????";
```

The compiled assembly stays relatively stable even when addresses change.

**2. Using Game's Own Functions**
Call the game's functions directly - they know their own structure:
```cpp
// Instead of reading struct offsets:
Player* player = playerArray[i];

// Call game's own function:
const wchar_t* name = GetPlayerName(player);
// ^ Game knows where the name is stored!
```

**3. Function Hooking**
Intercept game functions as they're called:
```cpp
// Hook the game's text rendering function
original_DrawText("PlayerName#1234", x, y);
// ^ We captured the string as it was being drawn!
```

**4. RTTI (Runtime Type Information)**
C++ games have metadata about their classes:
```cpp
// Game's class definition at runtime
class Player {
    // RTTI knows the layout!
};
```

---

## Comparison Table

| Feature | External | Internal |
|---------|----------|----------|
| **Offset Updates** | Every patch | Rarely needed |
| **Ban Risk** | Medium | EXTREME |
| **Complexity** | Low | High |
| **Robustness** | Breaks often | More stable |
| **Vanguard Detection** | Possible | Almost certain |
| **Administrator Required** | Sometimes | Always |
| **Setup Complexity** | Simple | C++ compilation needed |

---

## Internal Implementation Details

### Step 1: Build the DLL
```bash
cd backend
build_internal_dll.bat
```

This compiles `valorant_internal.cpp` into `valorant_internal.dll`.

### Step 2: DLL Injection Process
```
Python (injector.py)
    ↓
1. Find VALORANT.exe process ID
    ↓
2. OpenProcess(PROCESS_ALL_ACCESS)
    ↓
3. VirtualAllocEx - Allocate memory in VALORANT
    ↓
4. WriteProcessMemory - Write DLL path
    ↓
5. CreateRemoteThread - Call LoadLibrary
    ↓
VALORANT loads our DLL
    ↓
DLL runs inside VALORANT! (DllMain called)
```

### Step 3: DLL Finds Data (No Offsets!)

**Pattern Scanning:**
```cpp
// Find function by its compiled assembly signature
uintptr_t addr = FindPattern(
    "\x48\x8B\x05\x00\x00\x00\x00",  // MOV RAX, [RIP+offset]
    "xxx????"                          // Last 4 bytes are wildcard
);

// Follow the relative address
int32_t offset = *(int32_t*)(addr + 3);
GetPlayerArray = (func_ptr)(addr + 7 + offset);

// Now we can call the game's own function!
void* players = GetPlayerArray();
```

**Function Hooking:**
```cpp
// Redirect game function to our hook
original_GetPlayerName = game_GetPlayerName;
game_GetPlayerName = our_hook_GetPlayerName;

// When game calls GetPlayerName:
const wchar_t* our_hook_GetPlayerName(Player* p) {
    const wchar_t* name = original_GetPlayerName(p);
    
    // We now have the player name!
    SaveToSharedMemory(name);
    
    return name;  // Return to game so it works normally
}
```

### Step 4: Inter-Process Communication (IPC)

DLL (inside VALORANT) → Python (Vortex):

```cpp
// DLL creates shared memory
HANDLE hMemory = CreateFileMapping(
    INVALID_HANDLE_VALUE,
    NULL,
    PAGE_READWRITE,
    0,
    65536,
    "VortexValorantPlayerData"
);

// Write player data
SharedData* data = MapViewOfFile(hMemory, ...);
wcscpy(data->players[0].username, L"PlayerName#1234");
data->player_count = 1;
```

```python
# Python reads shared memory
handle = kernel32.OpenFileMappingA(0x0004, False, b"VortexValorantPlayerData")
data_ptr = kernel32.MapViewOfFile(handle, 0x0004, 0, 0, 65536)

player_count = ctypes.c_int.from_address(data_ptr).value
username = ctypes.wstring_at(data_ptr + 4)
```

---

## Why Internal is More Detectable

### Anti-Cheat Detection Methods

**1. Module Scanning**
Vanguard enumerates all loaded DLLs:
```
valorant.exe
  ├── game.dll
  ├── engine.dll
  ├── valorant_internal.dll ← SUSPICIOUS!
```

**2. Code Integrity Checks**
Vanguard verifies game code hasn't been modified:
```
Expected: 48 8B 05 12 34 56 78
Actual:   E9 AB CD EF 12 90 90  ← Hook detected!
```

**3. Process Handle Scanning**
Vanguard looks for suspicious handles:
```
OpenProcess(PROCESS_ALL_ACCESS) ← RED FLAG
CreateRemoteThread ← BAN TRIGGER
```

**4. Kernel-Mode Detection**
Vanguard runs in the kernel (ring 0) and can see EVERYTHING:
- Injected code
- Modified page protections
- Hooked functions
- Remote threads

### External is Safer (But Not Safe)

External reading is still risky but:
- ✅ No code injection
- ✅ No function hooks
- ✅ Stays outside the game process
- ❌ Still uses suspicious APIs (ReadProcessMemory)
- ❌ Can be detected via handle enumeration

---

## Recommended Approach

### For Research/Testing: Internal
- Faster to develop (no offset hunting)
- Test on throwaway accounts only
- Great for understanding game architecture
- Educational value

### For "Production" Use: External
- Lower ban risk (still risky!)
- Doesn't modify game code
- No compilation needed
- Just update offsets per patch

### Safest Option: Don't Use Either
- Use official Riot APIs
- Use approved overlays (Overwolf)
- Respect Terms of Service
- Keep your accounts

---

## Building the Internal DLL

### Requirements
- Visual Studio 2019+ (with C++ tools)
- OR MinGW-w64 compiler
- Windows SDK

### Build Steps

**Option 1: Visual Studio**
```bash
cd backend
"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
cl /LD /O2 /EHsc valorant_internal.cpp /link /OUT:valorant_internal.dll user32.lib psapi.lib
```

**Option 2: MinGW**
```bash
cd backend
g++ -shared -o valorant_internal.dll valorant_internal.cpp -std=c++17 -O2 -lpsapi -luser32
```

**Option 3: Use Build Script**
```bash
cd backend
build_internal_dll.bat
```

---

## Usage

### Enable Internal Mode

1. Build the DLL first (see above)
2. Open Vortex Settings
3. Enable "In-Game Memory Reading"
4. Select mode: **Internal (No offsets - EXTREMELY RISKY)**
5. Save settings
6. Start VALORANT
7. The DLL will inject automatically

### Check Status

```javascript
// In browser console or frontend:
fetch('/api/memory-reading/status')
  .then(r => r.json())
  .then(console.log);

// Response:
{
  "enabled": true,
  "mode": "internal",
  "settings_enabled": true
}
```

### Get Players

```javascript
fetch('/api/memory-reading/players')
  .then(r => r.json())
  .then(console.log);

// Response:
{
  "success": true,
  "mode": "internal",
  "players": [
    {
      "username": "PlayerOne",
      "tag": "1234",
      "agent": "Jett",
      "level": 150,
      "rank": "Immortal 2"
    }
  ]
}
```

---

## Troubleshooting

### "DLL not found"
- Build the DLL first using `build_internal_dll.bat`
- Check `backend/valorant_internal.dll` exists

### "Failed to inject DLL"
- Run Vortex as Administrator
- Vanguard may have blocked the injection (expected)
- Check if VALORANT is actually running

### "No player data"
- The DLL needs game-specific patterns implemented
- Current implementation is a skeleton
- You need to reverse engineer VALORANT to find actual patterns

### Banned?
- This was expected. Internal injection is highly detectable.
- Create a new account (or stop using memory reading)
- Consider using external mode or official APIs instead

---

## Legal & Ethical Notice

**This feature violates Riot Games' Terms of Service.**

- Account bans are expected, especially with internal mode
- No warranty or support provided
- Use for educational purposes only
- We do not encourage or endorse ToS violations
- You accept all risks by using this feature

---

## Technical Resources

### Learning More About Game Hacking

- **Guided Hacking** - Forum and courses
- **UnknownCheats** - Game hacking community
- **GuidedHacking YouTube** - Video tutorials
- **MPGH** - Multi-game hacking forum

### Tools for Development

- **x64dbg** - Debugger for reverse engineering
- **Cheat Engine** - Memory scanning and debugging
- **Ghidra** - Free reverse engineering tool
- **IDA Pro** - Professional disassembler
- **ReClass.NET** - Struct reconstruction

### Books

- "Game Hacking" by Nick Cano
- "Practical Reverse Engineering" by Bruce Dang
- "Reversing: Secrets of Reverse Engineering" by Eldad Eilam

---

## Summary

| Aspect | External | Internal |
|--------|----------|----------|
| Offset updates | Required | Not required |
| Implementation | `memory_reader.py` | `injector.py` + C++ DLL |
| Ban risk | Medium | EXTREME |
| Complexity | Low | High |
| Recommended | For production | For research only |

**Bottom line:** Internal mode doesn't need offset updates because it runs inside the game and uses the game's own code. But it's almost guaranteed to get you banned by Vanguard.
