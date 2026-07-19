[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
$skillsRoot = Join-Path $codexHome 'skills'
$skillTarget = Join-Path $skillsRoot 'codex-auto-model-router'
$legacySkillTarget = Join-Path $skillsRoot 'codex-model-router'
$agentTarget = Join-Path $codexHome 'agents'
$stageRoot = $null
$backupRoot = $null
$skillSwapped = $false
$legacySkillMoved = $false
$agentsChanged = $false
$completed = $false

$legacyPresets = @(
    'project-model-router.toml', 'project-model-router-low.toml', 'project-model-router-high.toml', 'project-model-router-xhigh.toml',
    'project-model-router-terra.toml', 'project-model-router-terra-low.toml', 'project-model-router-terra-high.toml', 'project-model-router-terra-xhigh.toml',
    'project-model-router-luna.toml', 'project-model-router-luna-low.toml', 'project-model-router-luna-high.toml', 'project-model-router-luna-xhigh.toml',
    'project-model-executor.toml', 'project-model-executor-low.toml', 'project-model-executor-high.toml', 'project-model-executor-xhigh.toml',
    'project-model-executor-terra.toml', 'project-model-executor-terra-low.toml', 'project-model-executor-terra-high.toml', 'project-model-executor-terra-xhigh.toml',
    'project-model-executor-luna.toml', 'project-model-executor-luna-low.toml', 'project-model-executor-luna-high.toml', 'project-model-executor-luna-xhigh.toml'
)

function Restore-OwnedAgents {
    Get-ChildItem -LiteralPath $agentTarget -File -Filter 'codex-auto-model-router*.toml' -ErrorAction SilentlyContinue | Remove-Item -Force
    Get-ChildItem -LiteralPath $agentTarget -File -Filter 'codex-auto-model-executor*.toml' -ErrorAction SilentlyContinue | Remove-Item -Force
    foreach ($name in $legacyPresets) {
        Remove-Item -LiteralPath (Join-Path $agentTarget $name) -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $agentBackup) {
        Get-ChildItem -LiteralPath $agentBackup -File -Filter '*.toml' | Move-Item -Destination $agentTarget -Force
    }
}

function Invoke-InjectedFailure([string]$Point) {
    if ($env:CODEX_AUTO_MODEL_ROUTER_INSTALL_FAIL_AT -eq $Point) {
        throw "Injected installer failure at $Point"
    }
}

function Test-FileContentEqual([string]$Left, [string]$Right) {
    $leftBytes = [IO.File]::ReadAllBytes($Left)
    $rightBytes = [IO.File]::ReadAllBytes($Right)
    if ($leftBytes.Length -ne $rightBytes.Length) { return $false }
    return [Convert]::ToBase64String($leftBytes) -ceq [Convert]::ToBase64String($rightBytes)
}

try {
    New-Item -ItemType Directory -Force -Path $skillsRoot, $agentTarget | Out-Null
    foreach ($existingTarget in @($skillTarget, $legacySkillTarget)) {
        if ((Test-Path -LiteralPath $existingTarget) -and -not (Get-Item -LiteralPath $existingTarget).PSIsContainer) {
            throw "Refusing to replace non-directory install target: $existingTarget"
        }
    }
    $stageRoot = Join-Path $skillsRoot ('.codex-auto-model-router.stage.' + [guid]::NewGuid())
    $backupRoot = Join-Path $skillsRoot ('.codex-auto-model-router.backup.' + [guid]::NewGuid())
    $stagedSkill = Join-Path $stageRoot 'skill'
    $stagedAgents = Join-Path $stageRoot 'agents'
    $skillBackup = Join-Path $backupRoot 'skill'
    $legacySkillBackup = Join-Path $backupRoot 'legacy-skill'
    $agentBackup = Join-Path $backupRoot 'agents'

    New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $stagedSkill 'agents'), (Join-Path $stagedSkill 'references'), (Join-Path $stagedSkill 'scripts'), $stagedAgents | Out-Null
    Copy-Item -LiteralPath (Join-Path $root 'SKILL.md') -Destination (Join-Path $stagedSkill 'SKILL.md')
    Copy-Item -LiteralPath (Join-Path $root 'agents/openai.yaml') -Destination (Join-Path $stagedSkill 'agents/openai.yaml')
    Get-ChildItem -LiteralPath (Join-Path $root 'references') -File -Filter '*.md' | Copy-Item -Destination (Join-Path $stagedSkill 'references') -Force
    Copy-Item -LiteralPath (Join-Path $root 'references/benchmark-evidence.json') -Destination (Join-Path $stagedSkill 'references/benchmark-evidence.json')
    Get-ChildItem -LiteralPath (Join-Path $root 'scripts') -File -Filter '*.py' | Copy-Item -Destination (Join-Path $stagedSkill 'scripts') -Force
    Get-ChildItem -LiteralPath (Join-Path $root 'codex-agents') -File -Filter '*.toml' | Copy-Item -Destination $stagedAgents -Force

    foreach ($source in @(
        (Join-Path $root 'SKILL.md'), (Join-Path $root 'agents/openai.yaml')
    ) + (Get-ChildItem -LiteralPath (Join-Path $root 'references') -File -Filter '*.md' | ForEach-Object { $_.FullName }) + @((Join-Path $root 'references/benchmark-evidence.json')) + (Get-ChildItem -LiteralPath (Join-Path $root 'scripts') -File -Filter '*.py' | ForEach-Object { $_.FullName })) {
        $relative = $source.Substring($root.Length).TrimStart([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
        if (-not (Test-FileContentEqual $source (Join-Path $stagedSkill $relative))) { throw "Staged payload verification failed: $relative" }
    }
    Get-ChildItem -LiteralPath (Join-Path $root 'codex-agents') -File -Filter '*.toml' | ForEach-Object {
        if (-not (Test-FileContentEqual $_.FullName (Join-Path $stagedAgents $_.Name))) { throw "Staged preset verification failed: $($_.Name)" }
    }

    if (Test-Path -LiteralPath $legacySkillTarget) {
        Move-Item -LiteralPath $legacySkillTarget -Destination $legacySkillBackup
        $legacySkillMoved = $true
    }
    Invoke-InjectedFailure 'after-legacy-backup'

    if (Test-Path -LiteralPath $skillTarget) { Move-Item -LiteralPath $skillTarget -Destination $skillBackup }
    $skillSwapped = $true
    Move-Item -LiteralPath $stagedSkill -Destination $skillTarget
    Invoke-InjectedFailure 'after-skill-swap'

    New-Item -ItemType Directory -Force -Path $agentBackup | Out-Null
    $ownedAgentPaths = @(
        (Get-ChildItem -LiteralPath $agentTarget -File -Filter 'codex-auto-model-router*.toml' -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
        (Get-ChildItem -LiteralPath $agentTarget -File -Filter 'codex-auto-model-executor*.toml' -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    )
    foreach ($name in $legacyPresets) {
        $legacyPreset = Join-Path $agentTarget $name
        if (Test-Path -LiteralPath $legacyPreset) { $ownedAgentPaths += $legacyPreset }
    }
    $ownedAgentPaths = @($ownedAgentPaths | Select-Object -Unique)
    $agentBackupCount = 0
    foreach ($ownedAgentPath in $ownedAgentPaths) {
        Copy-Item -LiteralPath $ownedAgentPath -Destination $agentBackup -Force
        $agentBackupCount += 1
        if ($agentBackupCount -eq 1) { Invoke-InjectedFailure 'during-agent-backup' }
    }
    $agentsChanged = $true
    foreach ($ownedAgentPath in $ownedAgentPaths) {
        Remove-Item -LiteralPath $ownedAgentPath -Force
    }
    Get-ChildItem -LiteralPath $stagedAgents -File -Filter '*.toml' | Move-Item -Destination $agentTarget
    Invoke-InjectedFailure 'after-agent-swap'

    $completed = $true
    Write-Output "Installed codex-auto-model-router into $codexHome"
    Write-Output 'Reconciled this project''s skill and custom-agent presets; migrated legacy names when present.'
    Write-Output 'Restart Codex to refresh skills and custom agents.'
}
catch {
    if ($agentsChanged) { Restore-OwnedAgents }
    if ($skillSwapped) {
        Remove-Item -LiteralPath $skillTarget -Recurse -Force -ErrorAction SilentlyContinue
        if ($null -ne (Get-Item -LiteralPath $skillBackup -Force -ErrorAction SilentlyContinue)) { Move-Item -LiteralPath $skillBackup -Destination $skillTarget }
    }
    if ($legacySkillMoved) {
        Remove-Item -LiteralPath $legacySkillTarget -Recurse -Force -ErrorAction SilentlyContinue
        if ($null -ne (Get-Item -LiteralPath $legacySkillBackup -Force -ErrorAction SilentlyContinue)) { Move-Item -LiteralPath $legacySkillBackup -Destination $legacySkillTarget }
    }
    throw
}
finally {
    if ($stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue }
    if ($backupRoot) { Remove-Item -LiteralPath $backupRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
