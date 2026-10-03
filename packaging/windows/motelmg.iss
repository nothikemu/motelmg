; Inno Setup script for the MotelMG Windows installer.
; Built automatically by packaging/build.py (needs Inno Setup 6: https://jrsoftware.org/isinfo.php)

#define AppName "MotelMG"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6E1C9A52-4B7D-4F3A-9C1E-2D7B5A8F0C31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=MotelMG
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\MotelMG.exe
UninstallDisplayName={#AppName} - Motel Management System
OutputDir=..\..\dist
OutputBaseFilename=MotelMG-Setup-{#AppVersion}
SetupIconFile=..\..\motelmg\resources\icons\app.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\MotelMG\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\MotelMG.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\MotelMG.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MotelMG.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Your data (database, backups, logs) lives in %LOCALAPPDATA%\MotelMG and is NOT removed on uninstall,
; so reinstalling or upgrading never loses reservations.
