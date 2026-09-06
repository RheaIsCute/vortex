# Memory Reading Feature

## ⚠️ WARNING ⚠️

**This feature uses direct process memory reading to access VALORANT game data. This may violate Riot Games' Terms of Service and could result in account bans, suspensions, or other penalties.**

**USE AT YOUR OWN RISK.**

## What is Memory Reading?

Memory reading allows Vortex to access information directly from VALORANT's running process memory, similar to how game cheats and overlays work. This can reveal hidden player information such as:

- Hidden usernames and tags (for players with privacy mode enabled)
- Real-time player stats
- In-game data not available through official APIs

## How It Works

The memory reader uses Windows API functions like:
- `OpenProcess` - Opens a handle to the VALORANT process
- `ReadProcessMemory` - Reads data from the process memory space
- Process snapshots - Finds the VALORANT process and module base addresses

This is the same technique used by:
- Game cheats and hacks
- Overlays (Discord, GeForce Experience)
- Performance monitoring tools
- External stat trackers

## Security & Anti-Cheat Considerations

### Vanguard Detection Risk

VALORANT uses Vanguard, Riot's kernel-level anti-cheat system. Vanguard can detect:
- Process handles opened with `PROCESS_VM_READ` permissions
- Suspicious `ReadProcessMemory` calls
- Pattern scanning and memory searches
- Known cheat signatures

**This feature could trigger Vanguard and result in an instant ban.**

### Why This Feature Exists

This feature is provided for:
1. **Research purposes** - Understanding how game memory works
2. **Advanced users** - Who accept the risks and want access to hidden data
3. **Testing environments** - Non-competitive/offline testing only

It is **NOT recommended for regular use** on accounts you care about.

## How to Enable

1. Open Vortex Settings (gear icon)
2. Expand "Advanced / Developer Settings"
3. Enable the toggle: **"Enable In-Game Memory Reading"**
   - Note the red warning icon and text
4. Save settings
5. The feature will attempt to attach when VALORANT is running

## API Endpoints

The following API endpoints are available:

### Enable Memory Reading
```
POST /api/memory-reading/enable
```
Attempts to attach to VALORANT process and enable memory reading.

### Disable Memory Reading
```
POST /api/memory-reading/disable
```
Detaches from VALORANT and disables memory reading.

### Check Status
```
GET /api/memory-reading/status
```
Returns whether memory reading is currently active.

### Get Players
```
GET /api/memory-reading/players
```
Returns player list extracted from game memory.

## Implementation Notes

### Memory Offsets

Game memory offsets change with **every VALORANT patch**. The current implementation in `backend/memory_reader.py` is a skeleton that requires:

1. **Reverse Engineering** - Finding player data structures
2. **Pattern Scanning** - Locating dynamic addresses
3. **Offset Updates** - Updating with each game patch
4. **Pointer Chains** - Following multi-level pointers

Without proper offsets, the reader will return empty data.

### Required Permissions

Memory reading requires:
- **PROCESS_VM_READ** - Read process virtual memory
- **PROCESS_QUERY_INFORMATION** - Query process information
- **Administrator privileges** (recommended) - Some operations may fail without elevation

### Limitations

- Offsets must be manually updated after each patch
- Only works while VALORANT is running
- May be blocked by anti-cheat at any time
- Can crash if accessing invalid memory regions
- Performance impact from continuous memory scanning

## Alternative Approaches

Instead of memory reading, consider:

1. **Official Riot APIs** - Safe, supported, no ban risk
2. **Local Client APIs** - Lockfile-authenticated endpoints
3. **Public Stats APIs** - HenrikDev, Tracker.gg
4. **Overwolf/VAL Tracker** - Approved overlay partners

Vortex already uses these safer methods for most data.

## Legal Disclaimer

This feature is provided for educational and research purposes only. The developers of Vortex:

- Do not encourage or endorse violating Terms of Service
- Are not responsible for any account penalties
- Provide no warranty or support for this feature
- May remove this feature at any time

**By enabling this feature, you acknowledge and accept all risks.**

## Technical Architecture

### Module Structure

```
backend/memory_reader.py
├── ValorantMemoryReader      # Low-level memory operations
│   ├── find_valorant_process()
│   ├── open_process()
│   ├── read_memory()
│   ├── read_string()
│   ├── find_pattern()
│   └── get_player_list()
│
├── MemoryReaderManager       # High-level manager
│   ├── enable()
│   ├── disable()
│   └── get_players()
│
└── Global Functions
    ├── is_memory_reading_enabled()
    ├── enable_memory_reading()
    ├── disable_memory_reading()
    └── get_memory_players()
```

### Data Flow

1. User enables toggle in Settings UI
2. Frontend saves `memory_reading_enabled: "1"` to database
3. User calls enable endpoint or setting is detected
4. Backend finds VALORANT process ID
5. Opens process handle with read permissions
6. Finds base module address
7. Scans/reads memory structures
8. Returns player data to frontend

## Development Notes

To implement actual memory reading:

1. **Use Cheat Engine** or similar tool to find player structures
2. **Document offsets** for current patch version
3. **Implement pattern scanning** for dynamic addresses
4. **Add pointer validation** to prevent crashes
5. **Test in practice mode** to avoid competitive bans
6. **Update with each patch** (weekly/bi-weekly)

Example offset structure:
```python
# VALORANT Patch 8.11 - Example offsets (FAKE)
OFFSETS = {
    "player_list": 0x12AB5678,
    "username": 0x80,
    "tag": 0x90,
    "agent_id": 0x120,
    "rank": 0x250,
}
```

## Community & Updates

If you're implementing real memory reading:

- Join reverse engineering communities (UnknownCheats, MPGH)
- Follow VALORANT patch notes
- Use signature scanning instead of static offsets
- Implement version checking to prevent invalid reads

---

**Remember: This is a high-risk feature. Use responsibly and at your own discretion.**
