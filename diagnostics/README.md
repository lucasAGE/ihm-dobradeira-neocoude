# Neocoude — kit de diagnóstico 0.3.0

Ferramentas independentes da IHM, sem instalação de dependências, sem abrir porta
serial, sem comandos de movimento e sem alterar serviços. A entrega 0.3.0 também
inclui a correção local do feedback em `ihm_esp32`; consulte
[CORRECAO_FEEDBACK.md](../docs/diagnostico/CORRECAO_FEEDBACK.md). O Raspberry ainda
não foi atualizado. Ladder, mapa, cliente Modbus e parâmetros de polling foram preservados.

O notebook não estava conectado à máquina nesta entrega. Nenhum resultado local
de Windows, WSL ou simulação comprova a saúde do Raspberry, CLP ou limite angular.

## Quando conectar à IHM_NEOCOUDE

Após `git pull` no notebook, gere o pacote que não é armazenado no Git:

```powershell
python diagnostics/build_field_package.py
```

A saída informa uma pasta nova contendo ZIP, checksums e scripts de extração.
Os relatórios locais e backups anteriores não entram nesse pacote. Para orientar
o assistente do outro computador, use o [prompt pronto](../docs/diagnostico/PROMPT_NOTEBOOK.txt).

Siga o [roteiro de atualização em campo](../docs/diagnostico/ATUALIZACAO_EM_CAMPO.md):
identificação da instalação, comparação de arquivos, backup verificado no
Raspberry e notebook, troca conjunta de backend/tela, testes de feedback e rollback.
Há uma [ficha para registrar o atendimento](../docs/diagnostico/FICHA_ATUALIZACAO.md).

O comparador abaixo é somente leitura e não importa/inicia a aplicação:

```bash
python diagnostics/check_release.py --installed-root ihm_esp32 --expect candidate
```

No alvo, usar o diretório realmente identificado e `--expect either` para a
primeira conferência. `audited_base`/`candidate` identificam arquivos conhecidos;
`mixed_versions`/`different_or_unavailable` exigem investigação antes de copiar.
Saída 0 significa correspondência com `--expect`; 2 significa divergência e 1
erro na execução/manifesto. Resultado não certifica a máquina ou o processo ativo.

## Feedback de sensores e encoder

Para o **Raspberry Pi 3B/3B+ informado pelo usuário**, USB direto entre notebook
e Raspberry não cria uma conexão de dados para sensores. Use a rede
`IHM_NEOCOUDE` ou Ethernet já configurada. Não use cabo USB-A ↔ USB-A entre as
portas host dos dois computadores. A micro-USB da família 3B é alimentação.
Referências: [hardware do 3B+](https://www.raspberrypi.com/products/raspberry-pi-3-model-b-plus/)
e [modelos com suporte a USB gadget](https://github.com/raspberrypi/rpi-usb-gadget).

Abra **[panel/live.html](panel/live.html)** no notebook conectado à rede:

1. Informe o IP do Raspberry, inicialmente `192.168.50.1`, e porta `8765`.
2. Clique **Observar sinais**. A conexão só ocorre ao clicar; dura até 120 s.
3. Acompanhe encoder bruto/ângulo, entradas, saídas, controles, estados, ângulos
   programados e contadores que o backend publicar.
4. Encerre e use **Exportar coleta**. O JSON abre também no painel offline.

O monitor recebe mensagens WS e não envia payload de aplicação. Não abre serial,
não instala nada no Raspberry e não exige que o SSH esteja funcionando. Uma única
conexão, 1.000 estados e 2 MiB limitam a sessão; a tela atualiza no máximo 4 vezes/s.
Limite de mensagem: 64 KiB após recebimento pelo navegador. O navegador pode
solicitar permissão de acesso à rede local; se bloquear `file://` → `ws://`, use
o coletor PowerShell abaixo e importe o JSON. Não desative segurança do navegador.

Observe em manutenção: o broadcast legado possui defeitos de concorrência
reproduzidos na auditoria e corrigidos na cópia local 0.3.0. A versão instalada
ainda precisa ser identificada. Valores exibidos permanecem históricos quando a
conexão termina. O botão **Encerrar** encerra somente a observação, não para a máquina.

**Limites do feedback atual:** o código identifica um encoder; não há evidência de
um segundo encoder nem mapeamento validado de corrente, pressão, temperatura
hidráulica ou tensão dos sensores. Entradas e saídas são bits do CLP, não medições
elétricas. `velocidade_rpm` é estimativa a partir do comando do inversor, não
tacômetro independente. `0/1` de contatos NF não deve ser interpretado como
“seguro/perigoso” sem o circuito e o Ladder.

O backend corrigido publica `null` e metadados por sinal quando a leitura falha.
O estado fica **DESCONHECIDO** se faltar uma leitura ou os bits de estado forem
inconsistentes. `false` e zero continuam sendo valores válidos quando efetivamente
lidos. E1/E7 e S3/S7, antes lidos e descartados, também são publicados.

O monitor exibe erro, última leitura OK e contadores quando recebe `read_quality`.
Se conectar a uma versão antiga, mantém **validade da leitura não informada**;
não consegue reconstruir uma falha já ocultada. Frequência de mensagens,
tentativas de polling e taxa de sucessos do encoder são distintas. A última
depende dos contadores novos; RTT Modbus ainda exige captura do barramento.

Para identificar o que o Windows reconheceu, sem abrir nenhuma porta COM:

```powershell
.\diagnostics\Get-NeocoudeUsb.ps1 -OutputPath .\diagnostics\output\usb-notebook-01.json
```

Esse inventário lista portas, USB e adaptadores/endereço de rede. Não lê sensores,
não transforma USB de alimentação em conexão de dados e não configura drivers.
Veja [sinais e limitações](../docs/diagnostico/FEEDBACK.md).

## Começar pelo notebook

Requisitos: Windows PowerShell 5.1 ou PowerShell 7, sem Python ou internet.
Conecte manualmente à rede `IHM_NEOCOUDE` quando estiver no local e execute:

```powershell
.\diagnostics\Test-Neocoude.ps1
```

O padrão é `192.168.50.1`, ping, TCP 22/80/8080/8765, GET HTTP em 8080 e
observação WebSocket por 10 segundos em 8765. Não envia mensagens de aplicação;
o protocolo WebSocket pode trocar seus próprios quadros de controle. Não segue
redirecionamentos HTTP, não executa o HTML retornado e não autentica por SSH.
HTTP e WS não usam proxy. A recepção limita mensagem a 64 KiB, tráfego a 2 MiB e
estado armazenado a 600 mensagens por coleta, além do limite de tempo.

```powershell
.\diagnostics\Test-Neocoude.ps1 -TargetAddress 192.168.50.1 -TimeoutMs 4000 -WebSocketSeconds 30
# Somente ping/TCP/HTTP, sem conexão WebSocket:
.\diagnostics\Test-Neocoude.ps1 -WebSocketSeconds 0
```

A saída fica em `diagnostics/output/windows-<data>.json`. Relatórios existentes
nunca são sobrescritos. `refused` e `timeout` são situações diferentes; ping
respondendo não comprova que o alvo é o Raspberry nem que SSH está ativo.

Abra [panel/index.html](panel/index.html) no navegador do notebook e use **Importar
relatórios JSON**. Aceita várias coletas, mantém a mais recente de cada tipo e
exporta o conjunto. Funciona como arquivo local, sem servidor, CDN ou internet.
Não há conexão ao equipamento pelo painel. Valores são fotografias arquivadas,
com origem e data, inclusive quando o backend informou um estado obsoleto.

## Coletar no Linux alvo

Requisito: Python 3.9 ou superior já instalado. Primeiro copie apenas a pasta
`diagnostics` para uma pasta de manutenção via pendrive ou SSH existente. Não
execute instaladores antigos, não ative o ambiente versionado neste repositório.
No terminal local ou SSH do Raspberry:

```bash
python3 diagnostics/collect_linux.py --output /tmp/neocoude-linux-01.json
```

O JSON inclui modelo real via Device Tree, CPU/RAM, temperatura, frequência,
flags de alimentação/throttling, kernel/firmware, OS, montagens/espaço, atividade
passiva de disco, interfaces/USB/drivers, rede/Wi-Fi, serviços e logs limitados.
Permissões e processos usando a serial são inspecionados sem abrir o dispositivo.

Depois de conferir `WorkingDirectory` e `ExecStart` reais, acrescente os caminhos
corretos. Estes são **exemplos do repositório**, não caminhos detectados no alvo:

```bash
python3 diagnostics/collect_linux.py \
  --app-root /home/pi/ihm_esp32 \
  --python /home/pi/ihm_esp32/venv/bin/python3 \
  --service ihm.service \
  --output /tmp/neocoude-linux-02.json
```

Sem `--python`, as bibliotecas inventariadas são as do **coletor**, que podem não
ser as do serviço. Sem `--app-root`, a aplicação fica `not_collected`. Copie o JSON
ao notebook e importe no painel. Uma coleta x86/WSL não identifica o Raspberry.

O coletor usa prioridade reduzida quando permitido, amostra CPU/disco por 1 s e
executa comandos sequenciais com timeout de 3 s (5 s para pacotes Python), saída
limitada a 64 KiB e limite de linhas nos journals. Não fica rodando em loop.
O tempo total depende das ferramentas disponíveis. Preferir `/tmp` ou pendrive
para a saída e não repetir continuamente durante produção.

`status: ok` significa apenas **comando coletado**, não **máquina aprovada**.
Ferramentas ausentes, logs vazios, flags zeradas e falta de permissão não excluem
defeitos. Os arquivos contêm IPs, nomes e logs privados; a remoção automática de
segredos é parcial. Revise antes de compartilhar.

## Comunicação RS-485 sem disputar a serial

O kit não cria um segundo mestre e não abre `/dev/ttyUSB0`, nem em modo de leitura.
Até abrir uma tty pode alterar sinais de controle ou consumir respostas da IHM.

Para CRC, latência e taxa de leituras, forneça uma captura **já existente**, com
requisição e resposta pareadas, obtida por logger aprovado ou analisador passivo
isolado. O analisador offline aceita somente leituras FC01/FC02/FC03/FC04, registra exceções,
timeouts, CRC/endereço/função/tamanho inválidos e percentis de latência.

Formato JSONL, uma transação por linha; timestamps precisam de fuso. Exemplo
**sintético**, não medido na máquina:

```json
{"request_at":"2026-11-09T12:00:00Z","response_at":"2026-11-09T12:00:00.025Z","request_hex":"01 03 00 00 00 01 84 0a","response_hex":"01 03 02 00 00 b8 44"}
{"request_at":"2026-11-09T12:00:01Z","request_hex":"01 03 00 00 00 01 84 0a","error":"timeout"}
```

```bash
python3 diagnostics/analyze_modbus.py captura.jsonl --output modbus-01.json
```

Limites: arquivo regular de até 32 MiB, 20 mil linhas, 64 KiB por linha,
primeiros 500 eventos no relatório. Dispositivos não são aceitos como captura.
As estatísticas agregam toda a captura aceita. Frequência é `(N-1)/(último-primeiro)`
entre timestamps; frequência de sucesso considera somente respostas válidas.
Uma captura descontínua não mede necessariamente a taxa sustentada da aplicação.
RTU não tem ID de transação; o pareamento depende da origem da captura.

WebSocket recebe `encoder_raw`, `encoder_degrees`, `poll_count` etc. O backend
corrigido acrescenta contadores de sucesso e erro por leitura, mas não fornece
CRC ou latência RTU. Esses campos ficam desconhecidos quando não há evidência.
Encoder imóvel não significa leitura travada.

## Inventário, backup e recuperação

```bash
python3 diagnostics/artifacts.py inventory --root ihm_esp32 --label auditoria-2026-11-09 --output manifest.json
# Comparar hashes com a instalação coletada:
python3 diagnostics/artifacts.py inventory --root ihm_esp32 --snapshot neocoude-linux-02.json --output comparacao.json
# Backup de arquivos explicitamente selecionados; escolha uma saída nova:
python3 diagnostics/artifacts.py backup --root ihm_esp32 --include main_server.py --include modbus_client.py --include modbus_map.py --include state_manager.py --include bend_logger.py --include wifi_manager.py --include requirements.txt --include static --include config --label antes-manutencao --output backup-aplicacao.zip
python3 diagnostics/artifacts.py verify backup-aplicacao.zip
python3 diagnostics/artifacts.py restore-staging backup-aplicacao.zip --destination restauracao-para-conferencia
```

Backup é seleção de arquivos, não imagem de SD nem ambiente Python completo.
Arquivos de configuração selecionados podem conter credenciais; mantenha o ZIP
privado. Arquivos mutáveis exigem janela de manutenção para consistência. O ZIP
tem manifesto, data, commit e SHA-256 de cada arquivo; o comando retorna SHA-256
do ZIP. A recuperação valida tudo antes de extrair, exige destino novo e nunca
ativa a cópia, sobrescreve a instalação ou reinicia serviço.

Detalhes: [auditoria](../docs/diagnostico/AUDITORIA.md),
[coleta e testes em campo](../docs/diagnostico/COLETA_EM_CAMPO.md),
[versionamento e recuperação](../docs/diagnostico/VERSIONAMENTO.md),
[validação executada](../docs/diagnostico/VALIDACAO.md).

## Testes seguros deste kit

Na raiz do repositório:

```bash
python -m unittest discover -s diagnostics/tests -v
node --test diagnostics/tests/test_feedback.cjs
node --check diagnostics/panel/panel.js
```

O teste Windows usa exclusivamente `127.0.0.1` e servidores simulados; em Linux é
explicitamente ignorado. Os testes compilam a classe de estado e métodos
selecionados pela AST, com cliente e logger simulados, sem importar/inicializar
a IHM. Há regressões das correções de feedback e testes de caracterização para
wrap/setpoints que continuam sem correção. Sucesso local não valida o equipamento.
Não execute descoberta de testes na raiz: testes históricos podem atuar no CLP.

Validação opcional do painel, com Chromium já instalado, sem pacotes npm:

```powershell
node diagnostics/tests/check_panel.cjs 'C:\caminho\chrome.exe' diagnostics/output
```
