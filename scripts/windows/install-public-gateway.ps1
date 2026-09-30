param(
    [Parameter(Mandatory)][string]$AccessAudience,
    [string]$TemplateGatewayEnvPath,
    [string]$AccessTeamDomain,
    [string]$AccessAllowedEmails,
    [string]$CloudflaredContainer
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$gatewayEnv = Join-Path $repoRoot "public\gateway.env"
$composeFile = Join-Path $repoRoot "compose.public.yaml"

function Read-EnvFile {
    param([Parameter(Mandatory)][string]$Path)
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        $values[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $values
}

if ($TemplateGatewayEnvPath) {
    if (-not (Test-Path -LiteralPath $TemplateGatewayEnvPath -PathType Leaf)) {
        throw "TemplateGatewayEnvPath does not exist."
    }
    $template = Read-EnvFile -Path $TemplateGatewayEnvPath
    if (-not $AccessTeamDomain -and $template.ContainsKey("ACCESS_TEAM_DOMAIN")) {
        $AccessTeamDomain = $template["ACCESS_TEAM_DOMAIN"]
    }
    if (-not $AccessAllowedEmails -and $template.ContainsKey("ACCESS_ALLOWED_EMAILS")) {
        $AccessAllowedEmails = $template["ACCESS_ALLOWED_EMAILS"]
    }
}

if (-not $AccessTeamDomain) {
    $AccessTeamDomain = Read-Host "Cloudflare Access team domain"
}
if (-not $AccessAllowedEmails) {
    $AccessAllowedEmails = Read-Host "Allowed Access email address(es), comma-separated"
}

$AccessTeamDomain = $AccessTeamDomain.Trim().ToLowerInvariant()
$AccessAudience = $AccessAudience.Trim()
$AccessAllowedEmails = $AccessAllowedEmails.Trim()

if ($AccessTeamDomain -notmatch '^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com$') {
    throw "Invalid Cloudflare Access team domain."
}
if ([string]::IsNullOrWhiteSpace($AccessAudience)) {
    throw "AccessAudience must not be empty."
}
if ([string]::IsNullOrWhiteSpace($AccessAllowedEmails)) {
    throw "AccessAllowedEmails must not be empty."
}

$lines = @(
    "ACCESS_TEAM_DOMAIN=$AccessTeamDomain",
    "ACCESS_AUD=$AccessAudience",
    "ACCESS_ALLOWED_EMAILS=$AccessAllowedEmails",
    "RATE_PER_MIN=120",
    "MAX_BODY_BYTES=2097152"
)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($gatewayEnv, ($lines -join [Environment]::NewLine) + [Environment]::NewLine, $utf8NoBom)

& docker compose -f $composeFile up -d
if ($LASTEXITCODE -ne 0) {
    throw "docker compose failed."
}

if ($CloudflaredContainer) {
    $network = "yfinance-mcp-public_edge"
    $networks = @(& docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' $CloudflaredContainer 2>$null)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the specified cloudflared container."
    }
    if ($networks -notcontains $network) {
        & docker network connect $network $CloudflaredContainer
        if ($LASTEXITCODE -ne 0) {
            throw "Could not connect the cloudflared container to the gateway network."
        }
    }
}

Write-Host "Protected gateway started."
Write-Host "Gateway network: yfinance-mcp-public_edge"
