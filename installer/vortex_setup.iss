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
Source: "..\dist\Vortex.exe"; DestDir: "{app}"; Flags: ignoreversion restartreplace

[Icons]
Name: "{group}\Vortex"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall Vortex"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Vortex"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Vortex"; Flags: nowait postinstall

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM {#AppExeName}"; Flags: runhidden; RunOnceId: "KillVortex"

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
  end;
end;
