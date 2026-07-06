; Inno Setup script for SRM-CAM.
; Wraps the PyInstaller one-folder build (dist/SRM-CAM/) into a single
; Setup.exe with Start-menu + optional desktop shortcut and an uninstaller.
;
; Build: compile with ISCC (Inno Setup Compiler), e.g.
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
; or just run packaging\build.ps1 which does PyInstaller + this in one go.

#define MyAppName "SRM-CAM"
#define MyAppVersion "0.2.6"
#define MyAppPublisher "DTU 62768 team"
#define MyAppExeName "SRM-CAM.exe"

[Setup]
; AppId uniquely identifies this app for upgrades/uninstall - never change it.
AppId={{1DC2AE10-B36F-47A4-BB7A-9F1C756D1BD7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=srm-cam.ico
OutputDir=..\dist_installer
OutputBaseFilename=SRM-CAM-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Dirs]
; Per-user workspace. The app also creates these at startup (that path is
; authoritative, e.g. for portable/dev runs); creating them here just makes
; the folders visible right after install.
Name: "{userdocs}\SRM-CAM"
Name: "{userdocs}\SRM-CAM\sessions"
Name: "{userdocs}\SRM-CAM\exports"
Name: "{userdocs}\SRM-CAM\photos"

[Files]
; The whole PyInstaller output folder (exe + _internal with Qt, numpy, etc.).
Source: "..\dist\SRM-CAM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

