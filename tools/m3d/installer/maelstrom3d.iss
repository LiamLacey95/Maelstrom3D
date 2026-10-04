; Maelstrom3D Windows installer (Inno Setup 6).
;
;   ISCC.exe /DAppVersion=5.2.2-m3d.2 /DSourceDir=<built app folder> /DOutputDir=<dir> tools\m3d\installer\maelstrom3d.iss
;
; SourceDir is the packaged app folder (blender.exe, Maelstrom3D.exe, 5.2\, ...), without a "portable" folder.
; Installs per user by default (no admin prompt); the setup offers "all users" too.

#ifndef AppVersion
  #error Pass /DAppVersion=...
#endif
#ifndef SourceDir
  #error Pass /DSourceDir=...
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

[Setup]
AppId={{DC58958A-9A27-4ACE-9C4E-7814297BCFC8}
AppName=Maelstrom3D
AppVersion={#AppVersion}
AppVerName=Maelstrom3D {#AppVersion}
AppPublisherURL=https://github.com/LiamLacey95/Maelstrom3D
AppSupportURL=https://github.com/LiamLacey95/Maelstrom3D/issues
DefaultDirName={autopf}\Maelstrom3D
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\..\..\COPYING
SetupIconFile=..\..\..\release\windows\icons\winblender.ico
UninstallDisplayIcon={app}\blender.exe
UninstallDisplayName=Maelstrom3D
OutputDir={#OutputDir}
OutputBaseFilename=Maelstrom3D-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "portable"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Maelstrom3D"; Filename: "{app}\Maelstrom3D.exe"
Name: "{autodesktop}\Maelstrom3D"; Filename: "{app}\Maelstrom3D.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Maelstrom3D.exe"; Description: "Start Maelstrom3D"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Python caches written next to the scripts at run time.
Type: filesandordirs; Name: "{app}\5.2"
