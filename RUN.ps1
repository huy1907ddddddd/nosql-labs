param([ValidateRange(1,5)][int]$Lab=1)
$ErrorActionPreference='Stop'
$env:TEMP=Join-Path $PSScriptRoot '.tmp'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$env:TMP=$env:TEMP
$env:HF_HOME=Join-Path $PSScriptRoot '.cache\huggingface'
$env:PYTHONUNBUFFERED='1'
$folders=@('01_MongoDB','02_Redis','03_Cassandra','04_Neo4j','05_Vector')
$files=@('mongo_lab.py','ticketrush.py','run_lab.py','campus.py','vector_lab.py')
$folder=Join-Path $PSScriptRoot $folders[$Lab-1]
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if(-not (Test-Path -LiteralPath $python)) {throw 'Chay: py -3.13 -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt; bai 5 cai them 05_Vector\requirements.txt'}
Push-Location $folder
try {
 if($Lab -ne 5) {
  & docker.exe compose up -d
  if($LASTEXITCODE -ne 0) {throw 'Docker chua san sang'}
  # The drivers retry readiness below; Cassandra also waits for all healthchecks.
  if($Lab -eq 1 -or $Lab -eq 2) {
   $service=if($Lab -eq 1) {'mongo'} else {'redis'}
   $ready=$false
   for($i=0;$i -lt 30;$i++) {
    if($Lab -eq 1) {& docker.exe compose exec -T $service mongosh --quiet --eval 'db.runCommand({ping:1}).ok' 2>$null | Out-Null}
    else {& docker.exe compose exec -T $service redis-cli ping 2>$null | Out-Null}
    if($LASTEXITCODE -eq 0) {$ready=$true;break}
    Start-Sleep -Seconds 2
   }
   if(-not $ready) {throw 'Database chua san sang'}
  }
 }
 if($Lab -eq 4) {
  $ready=$false
  for($i=0;$i -lt 60;$i++) {
   & docker.exe compose exec -T neo4j cypher-shell -u neo4j -p learnneo4j 'RETURN 1;' 2>$null | Out-Null
   if($LASTEXITCODE -eq 0) {$ready=$true;break}
   Start-Sleep -Seconds 2
  }
  if(-not $ready) {throw 'Neo4j chua san sang'}
 }
 & $python $files[$Lab-1] 2>&1 | Tee-Object -FilePath 'KET-QUA.txt'
 if($LASTEXITCODE -ne 0) {throw 'Bai lab chua PASS. Xem KET-QUA.txt'}
 if($Lab -eq 4) {
  & $python 'campus.py' profile 2>&1 | Tee-Object -FilePath 'PROFILE.txt'
  if($LASTEXITCODE -ne 0) {throw 'Loi do query plan'}
 }
} finally {Pop-Location}

