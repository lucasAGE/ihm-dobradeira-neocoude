# Quando conectar à IHM_NEOCOUDE — atualização e teste do feedback

Roteiro preparado em 09/11/2026. Aplicação candidata: **feedback 0.3.0**, baseada
no commit `0c720f569ef9f033e32f008fadd744888bd74f3d`. Revisão do roteiro: **r1**.
Nenhuma etapa foi executada na máquina. Os comandos abaixo são para a futura
manutenção, em ordem; não são um script para colar inteiro de uma vez.

**Sequência:** conectar → identificar instalação → conferir arquivos → parar a
IHM em manutenção → fazer e verificar backup → substituir três arquivos → iniciar
uma única instância → observar sinais → aceitar ou recuperar o backup.

O serviço da IHM não é o comando de parada do CLP. Antes de parar/iniciar o
serviço, a máquina deve estar na condição de manutenção definida pelo responsável,
sem possibilidade de movimento durante a intervenção. Fechar as telas de operação.
O roteiro não altera Ladder, setpoints, saídas, proteções, rede ou dependências.

## 0. Depois do git pull: gerar o pacote no notebook

Relatórios e ZIPs de `diagnostics/output` são privados/gerados e não entram no Git.
Depois de atualizar este repositório no **notebook**, execute em PowerShell:

```powershell
Set-Location 'E:\Dev\Neocoude'
$NeocoudePackage = python diagnostics/build_field_package.py | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar o pacote; parar' }
$NeocoudePackage.directory
```

O comando confere os oito arquivos de referência, gera e verifica um ZIP em uma
pasta nova e inclui os três scripts de extração com checksums. Não acessa a rede
da máquina nem substitui pacotes anteriores. Guarde o caminho impresso para a
etapa 3. O [prompt para o assistente do notebook](PROMPT_NOTEBOOK.txt) também está
versionado neste repositório.

## 1. Notebook Windows: abrir o atendimento e conferir acesso

Conectar manualmente à rede **IHM_NEOCOUDE**. Usar duas janelas: **PowerShell no
notebook** e **terminal Bash no Raspberry**. Os títulos abaixo indicam onde rodar.

**PowerShell — notebook:**

```powershell
Set-Location 'E:\Dev\Neocoude'
Get-Command ssh,scp,curl.exe,python -ErrorAction Stop
$NeocoudeIp = '192.168.50.1'
$NeocoudeCase = Join-Path (Get-Location) ('diagnostics\output\campo-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $NeocoudeCase -ErrorAction Stop
.\diagnostics\Test-Neocoude.ps1 -TargetAddress $NeocoudeIp -WebSocketSeconds 0 -OutputPath (Join-Path $NeocoudeCase 'rede-antes.json')
$NeocoudeUser = Read-Host 'Usuário existente no Raspberry, confirmado pelo responsável'
$NeocoudeSsh = '{0}@{1}' -f $NeocoudeUser,$NeocoudeIp
ssh $NeocoudeSsh
```

`192.168.50.1` é o endereço esperado no repositório, ainda a confirmar no local.
Não presumir usuário `pi`, criar usuário ou trocar senha. Na primeira conexão SSH,
conferir a identidade/fingerprint do equipamento; não desativar a conferência de
chave. `Connection refused` não é senha errada: usar o roteiro de
[acesso local/SSH](COLETA_EM_CAMPO.md#quando-ssh-responde-connection-refused).
Se não houver acesso administrativo existente, coletar pelo console HDMI/teclado
e resolver o acesso antes da atualização. Não regravar o cartão.
Se a execução de `.ps1` estiver bloqueada, usar uma invocação isolada de
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\diagnostics\Test-Neocoude.ps1`
com os mesmos argumentos; não mudar a política global do Windows.

## 2. Raspberry: identificar o que está rodando

**Bash — Raspberry, somente leitura:**

```bash
hostname
date --iso-8601=seconds
cat /proc/device-tree/model
cat /etc/os-release
python3 --version
systemctl list-units --type=service --all --no-pager | grep -Ei 'ihm|neocoude|dobradeira'
pgrep -af 'main_server|ihm_server|server_ihm'
sudo ss -ltnp
```

Escolher a unidade pelo processo que atende as portas **8080 e 8765**. Se houver
duas IHM, script fora do systemd, container ou outro gerenciador, **não usar os
blocos de substituição abaixo**: registrar a instalação e adaptar o procedimento.

```bash
read -r -p 'Unidade systemd confirmada (com .service): ' NEO_SERVICE
systemctl show "$NEO_SERVICE" --no-pager -p Id -p User -p Group -p WorkingDirectory -p ExecStart -p FragmentPath -p DropInPaths -p MainPID -p ActiveState -p NRestarts
sudo systemctl cat "$NEO_SERVICE"
```

Confirmar que `ExecStart` usa `main_server.py` da variante `ihm_esp32`. Conferir
usuário/grupo, diretório, intérprete, porta serial e argumentos. Se houver `--stub`,
o estado é simulado: não aceitar como leitura de sensores reais. O exemplo histórico
`/home/pi/ihm_esp32` não substitui essa identificação.

```bash
read -r -p 'Diretório absoluto que contém o main_server.py em execução: ' NEO_APP
read -r -p 'Caminho absoluto do Python usado no ExecStart: ' NEO_PY
NEO_APP=$(realpath -e -- "$NEO_APP")
test -f "$NEO_APP/main_server.py"
test -x "$NEO_PY"
NEO_PID=$(systemctl show "$NEO_SERVICE" -p MainPID --value)
test "$NEO_PID" -gt 0
sudo readlink -f "/proc/$NEO_PID/cwd"
sudo cat "/proc/$NEO_PID/cmdline" | tr '\0' ' '
printf '\n'
"$NEO_PY" --version
"$NEO_PY" -c 'import sys; assert sys.version_info >= (3,9), "Python 3.9+ necessário"; print(sys.executable)'
"$NEO_PY" -c 'from importlib.metadata import version; print({p:version(p) for p in ("pymodbus","websockets","aiohttp","pyserial")})'
```

Usar o caminho do venv no `ExecStart`, sem trocá-lo pelo Python de sistema ao
resolver symlinks. Pacote ausente, versão de Python incompatível, processo ou
caminho diferente: registrar e investigar; não executar `pip install`, `apt upgrade`
ou `git pull` na instalação.

Criar uma pasta privada de manutenção fora da aplicação:

```bash
umask 077
NEO_CASE=$(mktemp -d "$HOME/neocoude-campo-XXXXXXXX")
printf '%s\n' "$NEO_CASE"
printf 'SERVICE=%s\nAPP=%s\nPYTHON=%s\n' "$NEO_SERVICE" "$NEO_APP" "$NEO_PY" > "$NEO_CASE/identificacao.txt"
sudo systemctl cat "$NEO_SERVICE" > "$NEO_CASE/unidade-antes.txt"
systemctl show "$NEO_SERVICE" --no-pager > "$NEO_CASE/servico-antes.txt"
```

Guardar o caminho impresso. A pasta inclui dados privados da instalação.
Manter as variáveis desta sessão. Se reconectar, recuperá-las de `identificacao.txt`
digitando os valores; não executar esse arquivo como script.

## 3. Transferir o pacote e conferir a versão

Pacote preparado na etapa 0: `neocoude-campo-feedback-0.3.0-r1.zip`, dentro da
pasta nova indicada pelo gerador em `diagnostics/output/campo-feedback-0.3.0-r1-*`.
Ele reúne ferramentas, roteiro e os oito arquivos de referência; somente os três
indicados na etapa 5 serão substituídos. Não copiar o ZIP inteiro sobre a aplicação.

**PowerShell — notebook, segunda janela:** preencher os mesmos IP, usuário e
pasta local registrados na etapa 1. As variáveis não passam de uma janela à outra.

```powershell
Set-Location 'E:\Dev\Neocoude'
$NeocoudeIp = Read-Host 'IP confirmado do Raspberry'
$NeocoudeUser = Read-Host 'Mesmo usuário SSH da etapa 1'
$NeocoudeSsh = '{0}@{1}' -f $NeocoudeUser,$NeocoudeIp
$NeocoudeCase = (Resolve-Path -LiteralPath (Read-Host 'Pasta local criada na etapa 1')).Path
if (-not (Test-Path -LiteralPath $NeocoudeCase -PathType Container)) { throw 'Pasta local inválida' }
$NeocoudeBundleDir = (Resolve-Path -LiteralPath (Read-Host 'Pasta do pacote impressa na etapa 0')).Path
$NeocoudeArchive = Join-Path $NeocoudeBundleDir 'neocoude-campo-feedback-0.3.0-r1.zip'
$NeocoudeChecksums = Join-Path $NeocoudeBundleDir 'SHA256SUMS-campo-0.3.0-r1.txt'
$NeocoudeRemote = Read-Host 'Pasta de manutenção impressa no Raspberry (caminho absoluto)'
python diagnostics/artifacts.py verify $NeocoudeArchive
if ($LASTEXITCODE -ne 0) { throw 'Pacote local inválido; parar' }
scp $NeocoudeArchive $NeocoudeChecksums (Join-Path $NeocoudeBundleDir 'artifacts.py') (Join-Path $NeocoudeBundleDir 'common.py') (Join-Path $NeocoudeBundleDir 'collect_linux.py') "${NeocoudeSsh}:${NeocoudeRemote}/"
if ($LASTEXITCODE -ne 0) { throw 'Transferência incompleta; parar' }
```

Manter esta segunda janela PowerShell para as próximas etapas no notebook.
Não enviar a pasta `diagnostics/output` inteira.

**Bash — Raspberry:**

```bash
cd "$NEO_CASE"
sha256sum -c SHA256SUMS-campo-0.3.0-r1.txt
```

Todos os quatro arquivos precisam estar **OK**. Depois:

```bash
"$NEO_PY" "$NEO_CASE/artifacts.py" verify "$NEO_CASE/neocoude-campo-feedback-0.3.0-r1.zip"
"$NEO_PY" "$NEO_CASE/artifacts.py" restore-staging "$NEO_CASE/neocoude-campo-feedback-0.3.0-r1.zip" --destination "$NEO_CASE/pacote"
NEO_TOOLS="$NEO_CASE/pacote/diagnostics"
NEO_CANDIDATE="$NEO_CASE/pacote/ihm_esp32"
"$NEO_PY" "$NEO_TOOLS/check_release.py" --installed-root "$NEO_CANDIDATE" --expect candidate --output "$NEO_CASE/candidato-conferido.json"
"$NEO_PY" "$NEO_TOOLS/check_release.py" --installed-root "$NEO_APP" --expect either --output "$NEO_CASE/versao-antes.json"
```

Interpretar `source_state` e `matches_expected`:

| Resultado da instalação | Próximo passo |
|---|---|
| `audited_base`, `true` | A base dos arquivos coincide; seguir a preparação do backup |
| `candidate`, `true` | Os três arquivos corrigidos já estão presentes; não sobrescrever. Conferir processo/tela e seguir para observação |
| `mixed_versions` | Atualização parcial; não iniciar uma combinação de arquivos. Investigar ou recuperar um backup conhecido |
| `different_or_unavailable` | Arquivo alterado/ausente, permissão insuficiente ou symlink; comparar antes de qualquer substituição |

O verificador compara três arquivos da atualização e cinco de contexto: cliente,
mapa Modbus, logger, gerenciador Wi-Fi e requisitos. Aceita diferença **apenas** de
CRLF/LF e a registra. Commit igual não basta para uma instalação com alterações
locais. O check lê arquivos; não comprova que o processo já os carregou.

Guardar também a coleta real:

```bash
"$NEO_PY" "$NEO_TOOLS/collect_linux.py" --app-root "$NEO_APP" --python "$NEO_PY" --service "$NEO_SERVICE" --output "$NEO_CASE/linux-antes.json"
```

## 4. Parar somente a IHM e criar o backup real

Executar somente após confirmar a condição de manutenção da máquina. Não parar
hostapd, dnsmasq, SSH ou o sistema inteiro. Não abrir outra instância do servidor.

```bash
sudo systemctl stop "$NEO_SERVICE"
systemctl show "$NEO_SERVICE" -p ActiveState -p SubState -p MainPID --no-pager
pgrep -af 'main_server|ihm_server|server_ihm'
sudo ss -ltnp
```

Exigir **ActiveState=inactive**, **MainPID=0**, ausência da instância identificada
e portas da IHM liberadas. Se houver processo remanescente, não copiar nem usar
`kill -9` para prosseguir. A parada do serviço precisa terminar primeiro.

Criar backup de código, tela e dados/configuração locais, sem venv nem imagem SD:

```bash
(
  set -euo pipefail
  test "$(systemctl show "$NEO_SERVICE" -p ActiveState --value)" = inactive
  test "$(systemctl show "$NEO_SERVICE" -p MainPID --value)" = 0
  "$NEO_PY" "$NEO_TOOLS/check_release.py" --installed-root "$NEO_APP" --expect base --output "$NEO_CASE/versao-parada.json"
  extras=()
  for name in config wifi_config.json logs; do
    if [ -e "$NEO_APP/$name" ]; then extras+=(--include "$name"); fi
  done
  "$NEO_PY" "$NEO_TOOLS/artifacts.py" backup --root "$NEO_APP" --include main_server.py --include state_manager.py --include modbus_client.py --include modbus_map.py --include bend_logger.py --include wifi_manager.py --include requirements.txt --include static "${extras[@]}" --label antes-feedback-0.3.0 --output "$NEO_CASE/backup-aplicacao.zip"
  "$NEO_PY" "$NEO_TOOLS/artifacts.py" verify "$NEO_CASE/backup-aplicacao.zip"
  "$NEO_PY" "$NEO_TOOLS/artifacts.py" restore-staging "$NEO_CASE/backup-aplicacao.zip" --destination "$NEO_CASE/backup-conferido"
  "$NEO_PY" "$NEO_TOOLS/check_release.py" --installed-root "$NEO_CASE/backup-conferido" --expect base --output "$NEO_CASE/backup-versao.json"
  cd "$NEO_CASE"
  sha256sum backup-aplicacao.zip versao-parada.json unidade-antes.txt > BACKUP-SHA256SUMS.txt
)
```

Qualquer falha interrompe este bloco. Corrigir o backup antes de substituir arquivos.
Se houver logs acima de 200 MiB/5.000 arquivos, links simbólicos, dados externos ou
arquivos sem permissão de leitura, preparar o backup apropriado separadamente;
não apagar dados nem omitir silenciosamente arquivos para passar no teste.
`versao-parada.json` guarda os donos, grupos e modos originais dos oito arquivos.

**PowerShell — notebook:**

```powershell
scp "${NeocoudeSsh}:${NeocoudeRemote}/backup-aplicacao.zip" "${NeocoudeSsh}:${NeocoudeRemote}/BACKUP-SHA256SUMS.txt" "${NeocoudeSsh}:${NeocoudeRemote}/versao-parada.json" "${NeocoudeSsh}:${NeocoudeRemote}/unidade-antes.txt" $NeocoudeCase
if ($LASTEXITCODE -ne 0) { throw 'Cópia do backup incompleta; parar' }
python diagnostics/artifacts.py verify (Join-Path $NeocoudeCase 'backup-aplicacao.zip')
if ($LASTEXITCODE -ne 0) { throw 'Backup no notebook inválido; parar' }
foreach ($line in Get-Content (Join-Path $NeocoudeCase 'BACKUP-SHA256SUMS.txt')) {
    $expected,$name = $line -split '\s+',2
    $actual = (Get-FileHash -LiteralPath (Join-Path $NeocoudeCase $name) -Algorithm SHA256).Hash
    if ($actual.ToLowerInvariant() -ne $expected) { throw "Hash divergente: $name" }
}
```

Só seguir depois de verificar o backup no Raspberry **e** a cópia no notebook.

## 5. Atualizar backend e tela juntos

São exatamente: `main_server.py`, `state_manager.py` e `static/index.html`.
Conservar serviço, venv, configuração, dados, cliente e mapa Modbus existentes.

**Bash — Raspberry:** definir a função abaixo uma vez. Ela copia somente os três
arquivos, com a IHM parada, recuperando dono/grupo/modo do relatório anterior.
Não inicia serviço e não executa o código copiado.

```bash
neo_copy_three() (
  set -euo pipefail
  local source_root="$1"
  test "$(systemctl show "$NEO_SERVICE" -p ActiveState --value)" = inactive
  test "$(systemctl show "$NEO_SERVICE" -p MainPID --value)" = 0
  test -d "$NEO_APP/static"
  test ! -L "$NEO_APP/static"
  for name in main_server.py state_manager.py static/index.html; do
    test -f "$source_root/$name"
    test ! -L "$source_root/$name"
    test ! -L "$NEO_APP/$name"
    attrs=$("$NEO_PY" -c 'import json,sys; v=json.load(open(sys.argv[1]))["files"][sys.argv[2]]; print(v["uid"],v["gid"],format(int(v["mode"],8),"o"))' "$NEO_CASE/versao-parada.json" "$name")
    read -r file_uid file_gid file_mode <<< "$attrs"
    sudo install -T -o "$file_uid" -g "$file_gid" -m "$file_mode" -- "$source_root/$name" "$NEO_APP/$name"
  done
)
```

Conferir integridade e sintaxe antes de copiar; **compilar texto sem importar o
servidor** evita iniciar serial ou alterar a rede:

```bash
(
  set -euo pipefail
  cd "$NEO_CASE"
  sha256sum -c BACKUP-SHA256SUMS.txt
  "$NEO_PY" "$NEO_TOOLS/check_release.py" --installed-root "$NEO_APP" --expect base
  "$NEO_PY" "$NEO_TOOLS/check_release.py" --installed-root "$NEO_CANDIDATE" --expect candidate
  "$NEO_PY" -c 'import pathlib,sys; root=pathlib.Path(sys.argv[1]); [compile((root/n).read_text(encoding="utf-8"),str(root/n),"exec") for n in ("main_server.py","state_manager.py")]; print("Sintaxe OK; aplicação não executada")' "$NEO_CANDIDATE"
  neo_copy_three "$NEO_CANDIDATE"
  "$NEO_PY" "$NEO_TOOLS/check_release.py" --installed-root "$NEO_APP" --expect candidate --output "$NEO_CASE/versao-depois.json"
)
```

Não iniciar se o bloco falhar. Uma interrupção entre os arquivos deixa a IHM
parada e pode resultar em `mixed_versions`: usar a recuperação da etapa 8.

## 6. Iniciar uma única instância e conferir a tela nova

O `start` abaixo usa o serviço já existente; não executa `main_server.py` à parte,
não faz `daemon-reload` e não muda a unidade. A inicialização normal da aplicação
inclui seu gerenciador Wi-Fi existente; manter acesso local de recuperação se o
SSH cair. Não reconectar iniciando outra cópia do processo.

```bash
(
  set -euo pipefail
  test "$(systemctl show "$NEO_SERVICE" -p ActiveState --value)" = inactive
  "$NEO_PY" "$NEO_TOOLS/check_release.py" --installed-root "$NEO_APP" --expect candidate
  sudo systemctl start "$NEO_SERVICE"
  systemctl is-active --quiet "$NEO_SERVICE"
)
systemctl show "$NEO_SERVICE" -p ActiveState -p SubState -p MainPID -p NRestarts --no-pager
sudo journalctl -u "$NEO_SERVICE" --since '-5 min' --no-pager -n 120
sudo ss -ltnp
```

Confirmar uma instância, portas 8080/8765 no processo esperado e ausência de erro
de importação, traceback, serial ocupada ou reinício em loop. Guardar uma segunda
leitura de `NRestarts` após a observação; não deve aumentar nesse período.

**PowerShell — notebook:** conferir que a página servida corresponde ao arquivo
atualizado e que a resposta não veio de cache/redirecionamento:

```powershell
$NeocoudeHtml = Join-Path $NeocoudeCase 'tela-servida.html'
curl.exe --fail --silent --show-error --noproxy '*' "http://${NeocoudeIp}:8080/" --output $NeocoudeHtml
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível obter a tela; investigar' }
Get-FileHash -LiteralPath $NeocoudeHtml -Algorithm SHA256
Get-FileHash -LiteralPath 'E:\Dev\Neocoude\ihm_esp32\static\index.html' -Algorithm SHA256
```

O servidor desta variante lê o HTML como texto; CRLF pode virar LF na resposta.
Se os hashes brutos diferirem, comparar somente a normalização CRLF/LF:

```powershell
python -c "import pathlib,sys; a=pathlib.Path(sys.argv[1]).read_bytes().replace(b'\r\n',b'\n'); b=pathlib.Path(sys.argv[2]).read_bytes().replace(b'\r\n',b'\n'); assert a==b, 'Tela servida diferente'; print('Tela servida confere')" $NeocoudeHtml 'E:\Dev\Neocoude\ihm_esp32\static\index.html'
```

Depois abrir `http://192.168.50.1:8080/` e recarregar com **Ctrl+F5**. Não usar os
botões de motor, modo, pedal ou setpoint neste teste de feedback.

## 7. Observar sensores e encoder, sem comandar a máquina

Abrir no notebook `E:\Dev\Neocoude\diagnostics\panel\live.html`. Informar o IP
confirmado, porta `8765`, duração **60 segundos** e clicar **Observar sinais**.
Ao terminar, exportar a coleta para a pasta do atendimento. O limite de 2 MiB
pode encerrar antes de 60 s; nesse caso guardar a coleta e registrar a duração.

Alternativa PowerShell, uma sessão por vez:

```powershell
.\diagnostics\Test-Neocoude.ps1 -TargetAddress $NeocoudeIp -WebSocketSeconds 30 -TimeoutMs 4000 -OutputPath (Join-Path $NeocoudeCase 'feedback-depois.json')
```

Importar esse JSON em `diagnostics/panel/index.html`. Conferir também as mensagens
em **Coleta Windows e mensagens recebidas**, inclusive `feedback_version: 1`,
`feedback_session`, `read_quality` e `machine_state_error`.

| Conferência | Critério para considerar o feedback recebido corretamente |
|---|---|
| Versão | Arquivos candidatos conferidos, tela nova e `feedback_version=1` no processo ativo |
| Comunicação | Recepção contínua, sem erro de formato ou novo reinício do serviço; duração/gaps registrados |
| Encoder parado | Bruto inteiro 0–65535, qualidade `ok`, contador de sucessos e horário de leitura avançando, mesmo sem mudar o valor |
| Ângulo do encoder | Bruto, pulsos e ângulos presentes; registrar a conversão atual `%400` e relação 2:1, sem chamar isso de calibração |
| Entradas E0–E7 | Valor booleano quando lido, qualidade por entrada e horários avançando; reservas também identificadas |
| Saídas S0–S7 e controle | Bits recebidos com qualidade; isso não comprova atuação física dos contatores ou motor |
| Estado agregado | Um único estado ativo com leitura completa; se faltar leitura ou houver conflito, deve permanecer `DESCONHECIDO` |
| Erros | Comparar contadores no início/fim: sem novos erros na janela estável; erros antigos acumulados não somem após recuperação |
| Falha já existente | Sinal `null`/“Falha de leitura”, motivo e horário preservados; nunca substituir pela aparência de zero/`false` válido |
| Recuperação observada | O mesmo sinal volta a `ok` e a um valor válido; histórico de erros permanece |

O contador de polling não comprova leitura válida. A taxa calculada no notebook
é observada entre mensagens/contadores e pode ser afetada por mensagens acumuladas
na rede; não é medição de RTT nem garantia de frequência de amostragem no CLP.

### Variação física: registrar separadamente

Uma leitura estável comprova recepção, não resposta física do sensor. Para cada
sinal acessível, registrar valor antes/depois de uma mudança feita pelo responsável
usando o procedimento de manutenção da máquina, com movimento impedido pelo método
previsto. Não pressionar pedais com acionamento habilitado só para testar a tela,
não jumpear contatos e não desconectar sensores de proteção/barramento em operação.

Para o encoder, a variação deve ser conferida em bancada ou condição mecânica de
manutenção apropriada: registrar bruto inicial/final e referência observada. Não
deduzir deslocamento físico do salto normalizado de 399 para 400. Segundo encoder,
pressão, corrente e tensão não têm mapeamento confirmado nesta aplicação.

Se não houver condição apropriada para variação física ou falha controlada,
marcar o teste como **pendente**; os testes simulados locais não o substituem.
Nenhuma etapa aprova limite de 140°, sobrecorrida, parada de emergência ou produção.

Após a observação, no Raspberry:

```bash
systemctl show "$NEO_SERVICE" -p ActiveState -p MainPID -p NRestarts --no-pager > "$NEO_CASE/servico-depois.txt"
sudo journalctl -u "$NEO_SERVICE" --since '-10 min' --no-pager -n 200 > "$NEO_CASE/journal-depois.txt"
"$NEO_PY" "$NEO_TOOLS/collect_linux.py" --app-root "$NEO_APP" --python "$NEO_PY" --service "$NEO_SERVICE" --output "$NEO_CASE/linux-depois.json"
```

Guardar os relatórios no notebook e preencher a
[ficha do atendimento](FICHA_ATUALIZACAO.md). Resultado: **feedback aprovado**,
**inconclusivo** ou **falha**, sem confundir com liberação operacional da máquina.

## 8. Recuperação se a atualização falhar

Gatilhos: erro de importação, serviço reiniciando, mistura de versões, tela
incompatível, perda de feedback introduzida pela atualização ou erro novo que
não estava na coleta anterior. Manter a máquina em manutenção.

Usar o backup **desta instalação**, nunca a versão antiga do Git presumida como
idêntica. A função da etapa 5 precisa estar definida. Se o SSH cair, usar o acesso
local previsto; não apagar cartão, venv ou configuração de rede.

**Bash — Raspberry:**

```bash
sudo systemctl stop "$NEO_SERVICE"
(
  set -euo pipefail
  cd "$NEO_CASE"
  sha256sum -c BACKUP-SHA256SUMS.txt
  "$NEO_PY" "$NEO_TOOLS/artifacts.py" verify "$NEO_CASE/backup-aplicacao.zip"
  "$NEO_PY" "$NEO_TOOLS/artifacts.py" restore-staging "$NEO_CASE/backup-aplicacao.zip" --destination "$NEO_CASE/rollback-conferido"
  "$NEO_PY" "$NEO_TOOLS/check_release.py" --installed-root "$NEO_CASE/rollback-conferido" --expect base
  neo_copy_three "$NEO_CASE/rollback-conferido"
  "$NEO_PY" "$NEO_TOOLS/check_release.py" --installed-root "$NEO_APP" --expect base --output "$NEO_CASE/versao-rollback.json"
  sudo systemctl start "$NEO_SERVICE"
  systemctl is-active --quiet "$NEO_SERVICE"
)
```

Repetir estado do serviço, logs, portas e conferência da tela. Registrar a causa
da recuperação e manter o pacote candidato para análise. O código anterior volta
com suas limitações conhecidas de feedback; rollback não certifica sensores ou
parada. Dados/logs atuais e configuração não são sobrescritos por essa recuperação
dos três arquivos. Se uma etapa falhar, não iniciar uma cópia parcial.

## Referências e limites do roteiro

- [Raspberry Pi: acesso remoto por SSH e transferência de arquivos](https://www.raspberrypi.com/documentation/computers/remote-access.html).
- `systemctl --help`, `man systemctl` e `install --help` da instalação local.
- [Correções e testes locais](CORRECAO_FEEDBACK.md),
  [coleta inicial](COLETA_EM_CAMPO.md) e [versionamento/backup](VERSIONAMENTO.md).

Os comandos de mudança de serviço e cópia acima foram preparados para execução
futura; não foram rodados no Raspberry nesta entrega. A correspondência de código
é necessária, mas não valida hardware, fonte, Ladder, bibliotecas ou condição da máquina.
