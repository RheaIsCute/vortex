; Inno Setup script for Vortex | Valorant Account Manager.
; Compile with: ISCC installer\vortex_setup.iss /DAppVersion=4.3.0
; (AppVersion defaults below if not passed on the command line.)

#ifndef AppVersion
  #define AppVersion "4.3.0"
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
Source: "..\dist\Vortex\Vortex.exe"; DestDir: "{app}"; Flags: ignoreversion restartreplace
Source: "..\dist\Vortex\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

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
; Wipe the previous build's _internal before copying the new one, so files
; dropped between versions cannot linger and get loaded.
Type: filesandordirs; Name: "{app}\_internal"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  I: Integer;
begin
  for I := 1 to 3 do
  begin
    Exec(ExpandConstant('{cmd}'), '/C taskkill /F /IM {#AppExeName} >nul 2>&1',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(200);
  end;
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
