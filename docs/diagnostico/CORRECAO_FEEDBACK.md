# Correção do feedback — entrega 0.3.0

09/11/2026, America/Sao_Paulo. Implementação local autorizada após a auditoria.
Base Git: `0c720f569ef9f033e32f008fadd744888bd74f3d`. Sem commit, implantação,
conexão ao Raspberry, acesso serial ou movimento real. Não havia instruções
`AGENTS.md`/`AGENTS.override.md` aplicáveis ao projeto.

## Comportamento corrigido

| Situação | Resultado agora |
|---|---|
| Inicialização, antes da primeira leitura | Valores `null`, qualidade `not_read`, estado `DESCONHECIDO` |
| Entrada, saída ou controle retorna `None` | Campo `null`, qualidade `error`; outros bits válidos são preservados |
| Driver lança exceção ou retorna tipo fora do contrato | Campo `null` e erro registrado; as demais leituras continuam |
| Leitura válida retorna `false` ou zero | Valor preservado e qualidade `ok` |
| Falta uma leitura entre os estados, mesmo com `ST_IDLE=true` | Estado agregado `DESCONHECIDO`, endereço `null` |
| Nenhum estado ou vários estados ativos | `DESCONHECIDO`, com motivo de inconsistência |
| Todos os estados lidos, somente `ST_IDLE=true` | `PARADA`, conforme o CLP; não certifica parada física |
| Encoder falha depois de uma leitura boa | Bruto, pulsos, ângulos e movimento ficam `null`; não reutiliza ângulo antigo |
| Registro de processo/setpoint falha | Valor e aliases ficam `null`; alvo depende de dobra/setpoint disponíveis |
| Comunicação se recupera | Novos valores válidos reaparecem; contadores históricos de erro permanecem |
| Falha durante uma dobra observada | Não registra a falha como conclusão nem une observações separadas pela falha |

E1/E7 e S3/S7 agora aparecem no estado: já eram consultados, mas seus resultados
eram descartados. Não foram adicionadas consultas ao barramento. A escala do
encoder, `%400`, registradores, cliente Modbus, parâmetros seriais, frequências
de polling, Ladder e comandos de movimento não foram alterados.

O alias `pedal_segura` passa a refletir o bit lido, inclusive `null`; antes era
forçado a `false`. Isso corrige a informação exibida e não escreve no CLP nem
muda a configuração física do pedal.

## Contrato do feedback

`full_state` e `state_update` mantêm seus nomes e campos. Há uma mudança deliberada:
os valores de medição aceitam `null` quando desconhecidos. A tela em
`ihm_esp32/static/index.html` acompanha a alteração: mostra “Sem leitura”, trata
estado desconhecido sem cair em “PARADA” e impede inverter um toggle cujo valor
não foi lido. Não distribuir só o backend com a tela antiga.

Campos adicionais:

- `feedback_version: 1` e `feedback_session`: versão do contrato e identidade da
  instância, para não combinar contadores de processos diferentes.
- `read_quality["inputs.E6"]`, `read_quality["encoder_raw"]`, etc.: `status`
  (`not_read`, `ok`, `error`), `last_attempt_at`, `last_success_at`, `success_count`,
  `error_count` e `last_error`.
- `machine_state_error`: `not_read`, `read_failed`, `no_active_state`,
  `multiple_active_states` ou `poll_error`; `null` quando o estado é determinado.
- `poll_ok`: resultado das leituras agendadas naquele ciclo. `poll_count` continua
  contando tentativas. Um ciclo sem I/O pode ser bem-sucedido enquanto uma entrada
  ainda mantém erro da última consulta; consulte a qualidade individual.

Datas são UTC com fuso. A qualidade corresponde à última tentativa terminada;
não é certificação da instalação elétrica ou da atualidade física do sensor.
`modbus_connected` continua sendo a flag do cliente, separada de sucesso por leitura.
O wrapper retorna `None` para diversos erros: `read_failed` não inventa um diagnóstico
de CRC ou timeout que ele não forneceu. Exceções publicam somente seu tipo.

O monitor aceita a versão anterior sem metadados, identificando-a como validade
não informada. Com o backend corrigido, exibe falhas, última leitura OK e taxa
observada de sucessos do encoder entre contadores. Reset de contador, sessão nova
ou tempo inválido impedem uma taxa enganosa. RTT/CRC continuam exigindo captura RTU.

## Entrega por WebSocket

O broadcast calcula o delta e atualiza sua referência a partir da mesma cópia de
estado. Uma mudança ocorrida durante `await send()` fica para o próximo envio,
em vez de desaparecer. A iteração usa uma cópia do conjunto de clientes, evitando
que entrada/saída concorrente encerre a tarefa. Esses dois defeitos da auditoria
agora têm testes de regressão, em vez de testes que esperam a falha antiga.

## Validação local

Comandos executados na raiz do repositório:

| Comando / verificação | Resultado |
|---|---|
| `python -m unittest diagnostics.tests.test_backend_feedback diagnostics.tests.test_runtime_evidence -v` | 16 aprovados após corrigir o isolamento do console no fixture |
| `python -m unittest discover -s diagnostics/tests -v` | 34 aprovados no Windows |
| `wsl -d Ubuntu --cd /mnt/e/Dev/Neocoude -- python3 -m unittest discover -s diagnostics/tests -v` | 33 aprovados, 1 teste exclusivo de Windows ignorado |
| `node --test diagnostics/tests/test_feedback.cjs` | 14 aprovados, incluindo JSON gerado pela classe Python corrigida |
| `node diagnostics/tests/check_panel.cjs 'C:\Users\Lucas\AppData\Local\ms-playwright\chromium-1248\chrome-win64\chrome.exe' diagnostics/output/backend-feedback-0.3.0` | Monitor offline/ao vivo e tela existente aprovados; falha e recuperação verificadas no navegador |
| `node --check` em `feedback.js`, `live.js`, `panel.js` e `check_panel.cjs` | Sem erros de sintaxe |
| `ast.parse(..., feature_version=(3,9))` nos arquivos Python do kit e nos dois módulos operacionais alterados | 12 arquivos aceitos; execução real em Python 3.9/ARM não realizada |
| Parser PowerShell nos dois scripts | Sem erros de sintaxe |
| `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check` | Aprovado, preservando o CRLF já versionado no HTML |
| Comparação com HEAD de Ladder, cliente/mapa Modbus, logger, requisitos e serviços | Nenhuma alteração nesses arquivos |

Os testes da classe usam os métodos reais, extraídos pela AST, com cliente e
logger simulados. Nunca importam/iniciam a aplicação operacional. O teste de
transporte envia o JSON produzido por `get_state()` em um WebSocket de loopback,
com zero payloads de aplicação enviados pelo monitor. A tela operacional usa um
WebSocket simulado dentro do navegador, sem contato com a máquina. O teste Windows
confirma preservação dos metadados de erro também no coletor PowerShell.

A primeira execução dos testes de dobra teve duas falhas causadas pela impressão
de emojis do runtime no console Windows do fixture (`UnicodeEncodeError`). O
console foi substituído por um mock no ambiente isolado; os testes continuaram
verificando as chamadas do logger e passaram. Isso não foi uma medição do Raspberry.

O `git diff --check` sem opção inicialmente apontou os CRLF das linhas novas do
HTML como whitespace. Conferiu-se que o arquivo já era CRLF no HEAD e executou-se
o check com `cr-at-eol`, sem alterar configuração global ou normalizar o arquivo
inteiro. As capturas de falha no monitor e na IHM foram inspecionadas visualmente.

Não foi executado servidor real com as dependências da instalação, teste ARM,
ensaio de desempenho no Pi 3B/3B+, calibração, verificação elétrica, teste de
parada ou aprovação do limite angular. O pacote não resolve a relação entre
setpoints de staging e os registradores usados pelo Ladder.

## Quando houver acesso pela rede

O passo a passo com comandos Windows/Raspberry, backup, comparação de versão,
troca conjunta e rollback está em [ATUALIZACAO_EM_CAMPO.md](ATUALIZACAO_EM_CAMPO.md).

O monitor local já pode observar a versão instalada. A correção só passa a valer
no equipamento após atualizar a aplicação: conectar o notebook não instala o patch.

Identificar primeiro `ExecStart`, diretório real e hashes conforme o roteiro de
coleta. Comparar com esta base, guardar backup da instalação efetiva e revisar as
diferenças antes de substituir arquivos em manutenção. A atualização precisa reunir
`state_manager.py`, `main_server.py` e `static/index.html` da variante `ihm_esp32`.
O arquivo ZIP é um conjunto de arquivos para revisão, não instalador ou imagem SD.
Não sobrescrever uma variante diferente só porque tem nomes parecidos.

O rollback deve usar o backup da instalação efetiva, e não presumir que o HEAD
local é idêntico ao Raspberry. Após a atualização, conferir `feedback_version=1`,
qualidade e recuperação por métodos de teste aprovados no local. Não provocar
falhas em sensores de proteção nem desconectar o barramento durante operação.
