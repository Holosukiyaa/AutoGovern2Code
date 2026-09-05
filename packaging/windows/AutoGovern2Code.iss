#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#ifndef SourceRoot
  #error SourceRoot must be provided by the build script
#endif
#ifndef BuildRoot
  #error BuildRoot must be provided by the build script
#endif

[Setup]
AppId={{B174DCBF-0B86-4B9B-A545-636E06064AA1}
AppName=AutoGovern2Code
AppVersion={#MyAppVersion}
AppPublisher=AutoGovern2Code contributors
AppPublisherURL=https://github.com/Holosukiyaa/AutoGovern2Code
AppSupportURL=https://github.com/Holosukiyaa/AutoGovern2Code/issues
AppUpdatesURL=https://github.com/Holosukiyaa/AutoGovern2Code/releases
DefaultDirName={localappdata}\Programs\AutoGovern2Code
DefaultGroupName=AutoGovern2Code
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableWelcomePage=yes
DisableStartupPrompt=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
OutputDir={#BuildRoot}\installer
OutputBaseFilename=AutoGovern2Code-Setup-Windows-x64
UninstallDisplayIcon={app}\AutoGovern2Code.exe
ChangesEnvironment=yes
SetupLogging=yes
RestartIfNeededByRun=no
CloseApplications=yes
RestartApplications=no
AppMutex=Local\AutoGovern2Code.Desktop

[Files]
Source: "{#BuildRoot}\runtime\ag2c\*"; DestDir: "{app}\ag2c"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#BuildRoot}\runtime\tray-host\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#BuildRoot}\runtime\git\*"; DestDir: "{app}\git"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#SourceRoot}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\AutoGovern2Code"; Filename: "{app}\AutoGovern2Code.exe"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AutoGovern2Code"; ValueData: """{app}\AutoGovern2Code.exe"""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\AutoGovern2Code.exe"; ValueType: string; ValueName: ""; ValueData: "{app}\AutoGovern2Code.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\AutoGovern2Code.exe"; ValueType: string; ValueName: "Path"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\AutoGovern2Code"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\AutoGovern2Code.exe"; Description: "Launch AutoGovern2Code"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\ag2c\ag2c.exe"; Parameters: "skill uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveAutoGovern2CodeSkills"

[Code]
const
  UserEnvironmentKey = 'Environment';

function NormalizePathEntry(Value: String): String;
begin
  Value := Trim(Value);
  if (Length(Value) >= 2) and (Value[1] = '"') and (Value[Length(Value)] = '"') then
    Value := Copy(Value, 2, Length(Value) - 2);
  StringChangeEx(Value, '/', '\', True);
  while (Length(Value) > 3) and (Value[Length(Value)] = '\') do
    Delete(Value, Length(Value), 1);
  Result := Lowercase(Value);
end;

function PopPathEntry(var Remaining: String; var HasMore: Boolean): String;
var
  Separator: Integer;
begin
  Separator := Pos(';', Remaining);
  HasMore := Separator > 0;
  if HasMore then
  begin
    Result := Copy(Remaining, 1, Separator - 1);
    Delete(Remaining, 1, Separator);
  end
  else
  begin
    Result := Remaining;
    Remaining := '';
  end;
end;

function HasPathEntry(PathValue, Entry: String): Boolean;
var
  Current, Remaining: String;
  HasMore: Boolean;
begin
  Result := False;
  Remaining := PathValue;
  repeat
    Current := PopPathEntry(Remaining, HasMore);
    if NormalizePathEntry(Current) = NormalizePathEntry(Entry) then
    begin
      Result := True;
      Exit;
    end;
  until not HasMore;
end;

procedure AddInstallPath;
var
  CurrentPath, InstallPath, UpdatedPath: String;
  PathExists: Boolean;
begin
  InstallPath := ExpandConstant('{app}\ag2c');
  PathExists := RegValueExists(HKEY_CURRENT_USER, UserEnvironmentKey, 'Path');
  if PathExists then
  begin
    if not RegQueryStringValue(HKEY_CURRENT_USER, UserEnvironmentKey, 'Path', CurrentPath) then
      RaiseException('The existing user PATH is not a string value.');
  end
  else
    CurrentPath := '';
  if not HasPathEntry(CurrentPath, InstallPath) then
  begin
    if PathExists then
      UpdatedPath := CurrentPath + ';' + InstallPath
    else
      UpdatedPath := InstallPath;
    { RegWriteStringValue preserves an existing REG_EXPAND_SZ value type. }
    if not RegWriteStringValue(HKEY_CURRENT_USER, UserEnvironmentKey, 'Path', UpdatedPath) then
      RaiseException('Could not add AutoGovern2Code to the user PATH.');
    if not RegQueryStringValue(HKEY_CURRENT_USER, UserEnvironmentKey, 'Path', CurrentPath) then
      RaiseException('Could not read the user PATH after updating it.');
    if not HasPathEntry(CurrentPath, InstallPath) then
      RaiseException('AutoGovern2Code was not present in the user PATH after updating it.');
  end;
end;

procedure RemoveInstallPath;
var
  Current, CurrentPath, InstallPath, NewPath, Remaining: String;
  HasMore, KeptEntry: Boolean;
begin
  InstallPath := ExpandConstant('{app}\ag2c');
  if not RegQueryStringValue(HKEY_CURRENT_USER, UserEnvironmentKey, 'Path', CurrentPath) then
    Exit;
  Remaining := CurrentPath;
  NewPath := '';
  KeptEntry := False;
  repeat
    Current := PopPathEntry(Remaining, HasMore);
    if NormalizePathEntry(Current) <> NormalizePathEntry(InstallPath) then
    begin
      if KeptEntry then
        NewPath := NewPath + ';';
      NewPath := NewPath + Current;
      KeptEntry := True;
    end;
  until not HasMore;
  if not KeptEntry then
  begin
    if not RegDeleteValue(HKEY_CURRENT_USER, UserEnvironmentKey, 'Path') then
      RaiseException('Could not remove the AutoGovern2Code user PATH value.');
  end
  else if not RegWriteStringValue(HKEY_CURRENT_USER, UserEnvironmentKey, 'Path', NewPath) then
    RaiseException('Could not remove AutoGovern2Code from the user PATH.');
end;

procedure InstallSkills;
var
  ResultCode: Integer;
begin
  if not Exec(ExpandConstant('{app}\ag2c\ag2c.exe'), 'setup', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    RaiseException('Could not start the AutoGovern2Code setup: ' + SysErrorMessage(ResultCode));
  if ResultCode <> 0 then
    RaiseException('AutoGovern2Code setup failed with exit code ' + IntToStr(ResultCode) + '.');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    InstallSkills;
    AddInstallPath;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RemoveInstallPath;
end;
