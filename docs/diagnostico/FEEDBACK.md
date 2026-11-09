# Feedback e testes adicionais — kit 0.2.0

Registro histórico da etapa anterior. A correção local posterior, solicitada pelo
usuário, está em [CORRECAO_FEEDBACK.md](CORRECAO_FEEDBACK.md), versão 0.3.0.
As afirmações de runtime preservado/não corrigido abaixo descrevem a etapa 0.2.0.

Data: 09/11/2026. O usuário informou Raspberry Pi 3B ou 3B+ e intenção de ligar
USB direto ao notebook. Não foi coletado Device Tree da placa nem realizada
conexão à máquina nesta etapa.

## Conexão para observar os sinais

Na família 3B/3B+, USB direto não oferece o modo dispositivo necessário à ligação
de dados com o notebook; a micro-USB serve para alimentação. Use Wi-Fi
`IHM_NEOCOUDE` ou Ethernet já configurada. Não alterar boot/firmware, instalar
pacote gadget ou regravar cartão para tentar contornar uma limitação física.

Fontes: [Raspberry Pi 3B+](https://www.raspberrypi.com/products/raspberry-pi-3-model-b-plus/),
[USB gadget — modelos suportados](https://github.com/raspberrypi/rpi-usb-gadget) e
[hardware Raspberry Pi](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html).

O [monitor ao vivo](../../diagnostics/panel/live.html) abre por ação explícita um
cliente WebSocket de recepção. Padrão: `ws://192.168.50.1:8765/`. Sem senha/SSH,
requisições adicionais de polling, payload de comando ou acesso serial. Aceita
IPv4 locais/privados. Não há reconexão automática. Dura até 120 s, 1.000 estados
ou 2 MiB; a interface atualiza no máximo 4 vezes/s. Encerrar interrompe apenas
a observação, não para a máquina. Usar em manutenção: os defeitos do broadcast
antigo continuam presentes e a abertura de um cliente pode expor sua concorrência.

O script Windows também passa a preservar `inputs`, `outputs`, `states`,
`control_bits`, `encoder_degrees_disco`, seleção de dobra, peças e RPM informado.
Monitor e painel offline compartilham a interpretação de sinais e valores nulos.

## Sinais preparados

Há 44 campos previstos no monitor. Isso não significa 44 sensores físicos:
vários são bits de controle, projeções ou registradores do código do repositório.

| Grupo | O que pode chegar da IHM | O que não comprova |
|---|---|---|
| Encoder único mapeado | Bruto, pulsos normalizados, ângulos da IHM e disco | Calibração, segundo encoder, leitura recente ou parada segura |
| Entradas E0–E7 | Zero, pedais avanço/parada/recuo, segurança, emergência e reservas | Tensão elétrica, continuidade ou integridade do sensor |
| Saídas S0–S7 | Bits dos contatores/inversor, LEDs e reservas | Atuação física de motor/contator; não são sensores de movimento |
| Controle | Direções, modos, pedal mantido, zero, ângulo atingido, habilitação | Correspondência com Ladder residente ou proteção independente |
| Estados | Parada, aguardando, dobrando, retornando, completo, emergência, manual, calibração | Exclusividade dos estados ou ausência de falha de leitura |
| Setpoints | Ângulos programados 1–3 e alvo informado | Que o programa de parada usa esses registradores |
| Processo | Dobra selecionada, peças, RPM estimado do comando do inversor | Velocidade medida por tacômetro ou qualidade da produção |

E1/E7 e S3/S7 estão no mapa, mas os dicionários iniciais do runtime recente não
os incluem. Resultados desses nomes são ignorados nos métodos de leitura. O
monitor mostra ausência, sem inventar zero. Pressão, corrente, tensão da fonte/
sensores e temperatura hidráulica não têm mapeamento validado. Temperatura da
CPU pertence à coleta separada do Linux. A polaridade de contatos NF depende
da confirmação do circuito e do Ladder; não se rotula 0/1 como seguro/perigoso.

## Qualidade e tempo

- `0`, `false`, `null`, campo ausente e tipo inválido são distintos.
- Um novo `full_state` limpa os campos ausentes daquele snapshot. Deltas parciais
  preservam os demais campos do grupo.
- Por sinal: valor recebido, última recepção, mudanças observadas e qualidade.
  Data da recepção não é data da amostra no CLP. Campos constantes podem ser
  omitidos nos deltas; não se classifica automaticamente encoder constante como falha.
- Raw não é apagado quando o ângulo normalizado dá a volta; até 600 pontos da
  série observada ficam disponíveis na interpretação da coleta.
- Frequência de mensagens e frequência inferida de `poll_count` são separadas.
  Reset de contador, tempo regressivo ou ausente impedem taxas enganosas.
- Intervalos/silêncio no notebook não são RTT Modbus nem latência fim a fim.
  Taxa de leituras válidas do encoder e RTT continuam desconhecidos via WS.

O backend pode substituir falha por `false`. O observador não consegue distinguir
esse valor de leitura legítima sem metadados adicionais. Por isso os valores têm
**validade da leitura não informada**. Nulo/tipo inválido recebido é mostrado como
inválido. Não há indicador de aprovação do limite ou certeza de parada.

Para barramento, o analisador offline agora aceita também FC01/02. Confere bits
LSB primeiro, byte count, padding, CRC, endereço e função. FC01 e FC02 têm
semânticas distintas: não trocar uma pela outra presumindo equivalência no CLP.
Fonte: [especificação Modbus](https://www.modbus.org/file/secure/modbusprotocolspecification.pdf).

## Deficiências adicionais reproduzidas no código antigo

1. `read_inputs` transforma `None` em `false` e retorna sucesso. Uma entrada de
   emergência sem resposta pode ser publicada como bit falso ordinário.
2. Se todos os estados retornarem `None`, `read_machine_states` escolhe
   `ST_IDLE`/“PARADA” e retorna sucesso. Isso não prova máquina parada.
3. Entradas mapeadas ausentes do dicionário inicial são lidas e descartadas.
4. Raw=399 aparece como 179,55°; raw=400 como 0°, preservando raw=400. O salto
   deriva de `%400`, não comprova retorno físico ao zero.

Reproduções em [test_runtime_evidence.py](../../diagnostics/tests/test_runtime_evidence.py),
sem importar/iniciar a IHM ou conectar serial. O runtime não foi corrigido nesta
etapa. Instrumentação futura deverá publicar sucesso, erro, timestamp e contador
por leitura no único dono do cliente Modbus, sem um segundo mestre. Implantar
depende da identificação da versão instalada e teste de custo no Raspberry.

## Validação desta ampliação

| Execução | Resultado real |
|---|---|
| `python -m unittest discover -s diagnostics/tests -v` | 26 aprovados no Windows |
| `wsl -d Ubuntu --cd /mnt/e/Dev/Neocoude -- python3 -m unittest discover -s diagnostics/tests -v` | 25 aprovados, 1 exclusivo de Windows ignorado |
| `node --test diagnostics/tests/test_feedback.cjs` | 10 aprovados |
| `node diagnostics/tests/check_panel.cjs 'C:\Users\Lucas\AppData\Local\ms-playwright\chromium-1248\chrome-win64\chrome.exe' diagnostics/output/feedback-0.2.0-final` | Offline e monitor em loopback aprovados: importação, merge, exportação, nulos, ausentes, desktop/mobile e restrição de IP |
| Servidor simulado do navegador | Zero quadros de dados de aplicação recebidos; fechamento de protocolo permitido |
| `diagnostics/Get-NeocoudeUsb.ps1 -OutputPath diagnostics/output/usb-notebook-0.2.0.json` em PowerShell 5.1 | Inventário do notebook, sem abrir COM ou consultar Raspberry |
| `node --check` em live.js, feedback.js, panel.js | Sem erros de sintaxe |
| `ast.parse(..., feature_version=(3,9))` nos 8 arquivos Python do kit | Sintaxe aceita; não equivale a execução em Python 3.9 |
| `System.Management.Automation.Language.Parser.ParseFile` nos dois scripts PowerShell | Sem erros de sintaxe |
| `git diff --check` e comparação dos arquivos operacionais com HEAD | Sem erros de whitespace; runtime, Ladder e serviço preservados |
| Captura do monitor em viewport móvel | Inspecionada; formulário e status legíveis |

Os novos testes cobrem falha de sensores, wrap, descarte de campos, bits FC01/02,
padding, endereço broadcast, quantidades inválidas e corrupção de cada bit de
uma resposta conhecida. Os testes JavaScript cobrem nulos, deltas, full snapshot,
tipos/grupos inválidos, taxas, reset/tempo, preservação de raw e chaves indevidas.
Campos de intervalo e silêncio permanecem desconhecidos se o tempo da captura
estiver ausente ou regressivo, sem inventar intervalo zero.

**Não executado:** medição real de sensores/encoder, identificação da placa por
software, teste elétrico da fonte, comunicação com CLP, leitura por USB direto,
movimento, calibração ou aprovação do limite. O monitor roda no notebook e não
altera a instalação do Raspberry.
