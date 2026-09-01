; Inno Setup script for Vortex | Valorant Account Manager.
; Compile with: ISCC installer\vortex_setup.iss /DAppVersion=5.5.36
; (AppVersion defaults below if not passed on the command line.)

#ifndef AppVersion
  #define AppVersion "5.5.36"
#endif

#define AppName "Vortex"
#define AppPublisher "Vortex"
#define AppExeName "Vortex.exe"

; build.bat passes a short temporary staging path.  Keeping this override
; preserves direct ISCC builds while avoiding MAX_PATH omissions when this
; project lives in a deeply nested folder.
#ifndef BundleDir
  #define BundleDir "..\dist\Vortex"
#endif

[Setup]
AppId={{7B7C6A6E-6C3B-4E9C-9E3C-2E0B7B6C4B10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Vortex
DefaultGroupName=Vortex
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=VortexSetup
SetupIconFile=..\frontend\assets\logo.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
PrivilegesRequired=lowest
CloseApplications=force
CloseApplicationsFilter=*.exe
RestartApplications=no
AppMutex=Global\VortexAppMutex

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; The build is now a one-directory bundle (Vortex.exe + _internal\), not a
; single .exe - see build_exe.spec for why. Ship the whole folder.
Source: "{#BundleDir}\Vortex.exe"; DestDir: "{app}"; Flags: ignoreversion restartreplace
Source: "{#BundleDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Vortex"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall Vortex"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Vortex"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; skipifsilent: during a silent auto-update the background updater script
; relaunches Vortex itself. Without this flag both would launch it, which is
; why the update showed its error dialog twice.
Filename: "{app}\{#AppExeName}"; Description: "Launch Vortex"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM {#AppExeName}"; Flags: runhidden; RunOnceId: "KillVortex"

[InstallDelete]
; Clear the old Python bytecode and any stray _internal subfolders so a file
; removed between versions can't linger and get imported. NOT a full _internal
; wipe - that ran before the new files were confirmed writable, so a locked
; file plus a cancel left the install gutted. The [Files] section overwrites
; everything else in place (ignoreversion).
Type: filesandordirs; Name: "{app}\_internal\*.pyc"
Type: filesandordirs; Name: "{app}\_internal\**\__pycache__"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  I: Integer;
begin
  { Everything that can hold a file in _internal open. Vortex spawns
    msedgewebview2 children that outlive it, and Overwolf loads Vortex's
    VCRUNTIME140.dll via the process-directory DLL search - both lock files
    this install has to replace, which is what kept the update failing with
    "DeleteFile failed; code 5". Overwolf is restarted by Vortex on launch. }
  for I := 1 to 3 do
  begin
    Exec(ExpandConstant('{cmd}'),
         '/C taskkill /F /IM {#AppExeName} >nul 2>&1 & ' +
         'taskkill /F /IM Overwolf.exe /IM OverwolfBrowser.exe /IM OverwolfLauncher.exe >nul 2>&1',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(300);
  end;
  { WebView2 children of Vortex, matched by their command line. }
  Exec('powershell.exe',
       '-NoProfile -NonInteractive -Command "Get-CimInstance Win32_Process ' +
       '-Filter ""Name=''msedgewebview2.exe''"" | Where-Object { $_.CommandLine ' +
       '-match ''Programs.\\?Vortex'' } | ForEach-Object { Stop-Process -Id ' +
       '$_.ProcessId -Force -ErrorAction SilentlyContinue }"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(400);
  Result := '';
end;

procedure RefreshIconCache;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\ie4uinit.exe'), '-show', '', SW_HIDE,
       ewNoWait, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    RefreshIconCache;
    // A plain marker the updater can read back after a silent install to
    // confirm the files it just ran actually landed. A silent /VERYSILENT
    // run can report exit code 0 while genuinely changing nothing - most
    // commonly Windows Defender or another AV quarantining/blocking the
    // freshly-downloaded, unsigned installer mid-run without failing the
    // process outright - so the exit code alone isn't proof of anything.
    SaveStringToFile(ExpandConstant('{app}\installed_version.txt'), '{#AppVersion}', False);
  end;
end;
