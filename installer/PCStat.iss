; Inno Setup 6 — собирает один установщик вокруг PyInstaller onefile (dist\PCStat.exe).
; Запуск: ISCC.exe PCStat.iss из каталога installer (или через scripts\build_installer.ps1).

#define MyAppName "PC Stat"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "PC Stat"
#define MyAppExeName "PCStat.exe"
; Стабильный AppId — не менять между выпусками, чтобы «обновление» видело ту же программу.
#define MyAppId "{{E7F2B8C4-1A9D-4F3E-8C2B-5D6E9F0A1B3C}}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=PCStat-Setup
SourceDir=..
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=no
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64

[Languages]
; При установленном языковом пакете можно добавить: Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
