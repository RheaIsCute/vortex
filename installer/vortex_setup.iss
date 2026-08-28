; Inno Setup script for Vortex | Valorant Account Manager.
; Compile with: ISCC installer\vortex_setup.iss /DAppVersion=3.0.0
; (AppVersion defaults below if not passed on the command line.)

#ifndef AppVersion
  #define AppVersion "3.0.0"
#endif

#define AppName "Vortex"
#define AppPublisher "Vortex"
#define AppExeName "Vortex.exe"

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
; Always per-user, never admin - no elevation dialog/override needed. Inno
; Setup's PrivilegesRequiredOverridesAllowed forces Setup.exe to relaunch
; itself and verify the relaunched process's image path matches the
; original exactly; when launched from a background/detached process (as
; our in-app auto-updater does) that self-check can spuriously fail with
; "Security validation failure: parent process has different executable!"
; and dump the user back at a fresh wizard. Since we never need the
; per-user/per-machine choice, removing the override avoids that relaunch
; entirely.
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\Vortex.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Vortex"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall Vortex"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Vortex"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Vortex"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Vortex must not be running when we try to delete it - Windows won't
; remove a locked .exe, which previously left Vortex.exe behind after an
; uninstall. This runs before the uninstaller deletes any files.
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM {#AppExeName} /T"; Flags: runhidden; RunOnceId: "KillVortex"

[UninstallDelete]
; Scoped to the install dir only. The user's accounts live in
; %LOCALAPPDATA%\Vortex\database.sqlite and are deliberately preserved
; so reinstalling or updating keeps their data.
Type: filesandordirs; Name: "{app}"

[Code]
{ Close any running instance BEFORE files are copied. The old script did
  this from [Run], which fires after installation - far too late to
  release the file lock during an in-app auto-update. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{cmd}'), '/C taskkill /F /IM {#AppExeName} /T',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);
  Result := '';
end;

{ Windows caches extracted icon bitmaps per shortcut path and doesn't
  always notice when the target .exe's embedded icon changes underneath
  it - users who installed an early build (with the old, poorly-cropped
  icon) can keep seeing it on their taskbar/desktop/Start Menu even after
  updating to a build with the corrected icon. ie4uinit.exe -show asks
  Explorer to rebuild its icon cache without restarting explorer.exe, so
  there's no visible disruption (no taskbar flicker). Recreating the
  shortcuts first (the [Icons] section already does this on every
  install) plus this refresh clears the stale bitmap for most users. }
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
    RefreshIconCache;
end;
