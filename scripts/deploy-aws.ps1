[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Region,

    [Parameter(Mandatory)]
    [string]$ApiSecretArn,

    [string]$StackName = "agentic-chatbot",
    [string]$RepositoryName = "agentic-chatbot",
    [string]$AllowedCidr = "0.0.0.0/0",
    [string]$ImageTag
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

foreach ($command in "aws", "docker") {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command '$command' was not found. Install it and try again."
    }
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker is not running. Start Docker Desktop and try again."
}

$accountId = aws sts get-caller-identity --query Account --output text --region $Region
if ($LASTEXITCODE -ne 0 -or -not $accountId) {
    throw "AWS authentication failed. Run 'aws configure sso' and 'aws sso login' first."
}

if (-not $ImageTag) {
    $gitCommit = git rev-parse --short HEAD 2>$null
    $ImageTag = if ($LASTEXITCODE -eq 0 -and $gitCommit) {
        $gitCommit
    } else {
        Get-Date -Format "yyyyMMddHHmmss"
    }
}

$repositoryUri = aws ecr describe-repositories `
    --repository-names $RepositoryName `
    --region $Region `
    --query "repositories[0].repositoryUri" `
    --output text 2>$null

if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating ECR repository '$RepositoryName'..."
    $repositoryUri = aws ecr create-repository `
        --repository-name $RepositoryName `
        --region $Region `
        --image-scanning-configuration scanOnPush=true `
        --encryption-configuration encryptionType=AES256 `
        --query "repository.repositoryUri" `
        --output text
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the ECR repository."
    }
}

$registry = "$accountId.dkr.ecr.$Region.amazonaws.com"
aws ecr get-login-password --region $Region |
    docker login --username AWS --password-stdin $registry
if ($LASTEXITCODE -ne 0) {
    throw "Docker could not authenticate with ECR."
}

$localImage = "${RepositoryName}:${ImageTag}"
$taggedImage = "${repositoryUri}:${ImageTag}"

docker build --pull --tag $localImage .
if ($LASTEXITCODE -ne 0) {
    throw "Docker image build failed."
}

docker tag $localImage $taggedImage
docker push $taggedImage
if ($LASTEXITCODE -ne 0) {
    throw "Docker image push failed."
}

$imageDigest = aws ecr describe-images `
    --repository-name $RepositoryName `
    --image-ids "imageTag=$ImageTag" `
    --region $Region `
    --query "imageDetails[0].imageDigest" `
    --output text
if ($LASTEXITCODE -ne 0 -or -not $imageDigest) {
    throw "Could not resolve the pushed image digest."
}

$imageUri = "${repositoryUri}@${imageDigest}"

aws cloudformation deploy `
    --template-file infrastructure/aws.yml `
    --stack-name $StackName `
    --region $Region `
    --capabilities CAPABILITY_IAM `
    --no-fail-on-empty-changeset `
    --parameter-overrides `
        "ImageUri=$imageUri" `
        "ApiSecretArn=$ApiSecretArn" `
        "AllowedCidr=$AllowedCidr"
if ($LASTEXITCODE -ne 0) {
    throw "CloudFormation deployment failed."
}

$applicationUrl = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $Region `
    --query "Stacks[0].Outputs[?OutputKey=='ApplicationUrl'].OutputValue | [0]" `
    --output text

Write-Host "Deployment complete."
Write-Host "Image: $imageUri"
Write-Host "Application: $applicationUrl"