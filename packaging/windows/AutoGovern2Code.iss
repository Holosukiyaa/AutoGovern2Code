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
UninstallDisplayIcon={app}\ag2c\ag2c.exe
ChangesEnvironment=yes
SetupLogging=yes
RestartIfNeededByRun=no

[Files]
Source: "{#BuildRoot}\runtime\ag2c\*"; DestDir: "{app}\ag2c"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceRoot}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

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

function HasPathEntry(PathValue, Entry: String): Boolean;
var
  Entries: TArrayOfString;
  Index: Integer;
begin
  Result := False;
  Entries := SplitString(PathValue, ';');
  for Index := 0 to GetArrayLength(Entries) - 1 do
    if NormalizePathEntry(Entries[Index]) = NormalizePathEntry(Entry) then
    begin
      Result := True;
      Exit;
    end;
end;

procedure AddInstallPath;
var
  CurrentPath, InstallPath: String;
begin
  InstallPath := ExpandConstant('{app}\ag2c');
  if not RegQueryStringValue(HKEY_CURRENT_USER, UserEnvironmentKey, 'Path', CurrentPath) then
    CurrentPath := '';
  if not HasPathEntry(CurrentPath, InstallPath) then
  begin
    if (CurrentPath <> '') and (CurrentPath[Length(CurrentPath)] <> ';') then
      CurrentPath := CurrentPath + ';';
    RegWriteExpandStringValue(HKEY_CURRENT_USER, UserEnvironmentKey, 'Path', CurrentPath + InstallPath);
  end;
end;

procedure RemoveInstallPath;
var
  CurrentPath, InstallPath, NewPath: String;
  Entries: TArrayOfString;
  Index: Integer;
  KeptEntry: Boolean;
begin
  InstallPath := ExpandConstant('{app}\ag2c');
  if not RegQueryStringValue(HKEY_CURRENT_USER, UserEnvironmentKey, 'Path', CurrentPath) then
    Exit;
  Entries := SplitString(CurrentPath, ';');
  NewPath := '';
  KeptEntry := False;
  for Index := 0 to GetArrayLength(Entries) - 1 do
    if NormalizePathEntry(Entries[Index]) <> NormalizePathEntry(InstallPath) then
    begin
      if KeptEntry then
        NewPath := NewPath + ';';
      NewPath := NewPath + Entries[Index];
      KeptEntry := True;
    end;
  if not KeptEntry then
    RegDeleteValue(HKEY_CURRENT_USER, UserEnvironmentKey, 'Path')
  else
    RegWriteExpandStringValue(HKEY_CURRENT_USER, UserEnvironmentKey, 'Path', NewPath);
end;

procedure InstallSkills;
var
  ResultCode: Integer;
begin
  if not Exec(ExpandConstant('{app}\ag2c\ag2c.exe'), 'setup', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    RaiseException('Could not start the AutoGovern2Code setup: ' + SysErrorMessage(ResultCode));
  if ResultCode <> 0 then
    RaiseException(Fmt('AutoGovern2Code setup failed with exit code %d.', [ResultCode]));
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
