# Auditoria da plataforma Neocoude

Data: **09/11/2026**, America/Sao_Paulo. Base:
`lucaswjunges/ihm-dobradeira-neocoude`, branch `master`, commit
`0c720f569ef9f033e32f008fadd744888bd74f3d` (08/02/2026).

Ampliação posterior no mesmo dia: o usuário informou Pi 3B/3B+ e intenção de
ligação USB direta. Foram acrescentados monitor de recepção, sinais individuais
e novos testes, incluindo falha de sensores apresentada como `false`/“PARADA”.
Consulte [FEEDBACK.md](FEEDBACK.md). A identificação por software do equipamento
e as medições físicas continuam pendentes.

Correção posterior autorizada: [CORRECAO_FEEDBACK.md](CORRECAO_FEEDBACK.md)
documenta as alterações locais no feedback, incluindo A01/A02/A04 e os casos
de `false`/“PARADA”. Os achados e números de linha abaixo registram a base auditada;
não representam a situação da cópia corrigida nem prova de implantação no Raspberry.

## Escopo e evidência disponível

A pasta `E:\Dev\Neocoude` estava vazia e recebeu um clone do repositório público
encontrado na conexão GitHub. Não havia `AGENTS.md`/`AGENTS.override.md` aplicável.
Foram preservados branches, históricos, configurações, Ladder e código operacional.
Não foi necessário renomear a pasta: o nome do equipamento é NEOCOUDE-HD-15.

O usuário informou que o notebook **não está conectado à IHM_NEOCOUDE**. Não houve
ping, SSH, acesso ao Raspberry, leitura serial, escrita em CLP ou movimento real.
O histórico do conversor DC-DC e a falha em 140° são relatos a investigar, não
causas confirmadas. Nenhuma imagem nova foi gerada e nenhum pacote foi atualizado.

Nesta auditoria, **confirmado no código** descreve a versão clonada; **reproduzido
isoladamente** usa objetos simulados; **hipótese** precisa de medição; **não
executado** não equivale a aprovado. Textos antigos intitulados “100% validado”
não identificam a versão efetivamente instalada hoje.

## Arquitetura e versões encontradas

| Camada | Evidência do repositório | Instalação real |
|---|---|---|
| Hardware | `ihm_esp32/README.md` afirma Pi 3B+, USB–RS485 e Wi-Fi interno/USB | Modelo, RAM, SoC, chip Wi-Fi e fonte não identificados |
| Linux/firmware | Configurações Linux/systemd presentes; não há inventário completo do OS | Distribuição, kernel, firmware e arquitetura desconhecidos |
| Python | `ihm_esp32/venv/pyvenv.cfg` registra Python 3.11.2 e caminho de outra instalação | Intérprete do `ExecStart` desconhecido |
| Bibliotecas | Metadados versionados: pymodbus 3.7.4, websockets 15.0.1, aiohttp 3.13.2, pyserial 3.5 | Não são prova de pacotes instalados atualmente |
| Aplicação | Gerações na raiz, em `ihm` e em `ihm_esp32`; último commit altera principalmente `ihm_esp32` | Entry point e hashes precisam ser coletados |
| Serviços | `ihm_esp32/config/ihm.service` aponta `/home/pi/ihm_esp32/main_server.py`; `ihm-web.service` da raiz aponta outro usuário/servidor | Unidade habilitada, caminho, argumentos e reinícios desconhecidos |
| Rede | AP `wlan0`, IP 192.168.50.1/24, DHCP .10–.20 em config; servidor recente HTTP 8080 e WS 8765 | hostapd/dnsmasq/dhcpcd/NetworkManager efetivos precisam ser lidos |
| Serial | Cliente recente: `/dev/ttyUSB0`, 57600, 8N2, slave 1, timeout 0,5 s | Porta, conversor, permissões e parâmetros do CLP a confirmar |
| Ladder/imagem | Muitas variantes `.sup`/`.lad`; nenhuma imagem `.img`, `.img.gz`, `.img.xz` ou `.iso` rastreada | Programa residente e imagem do cartão não fornecidos |

O README da raiz ainda descreve encoder de 32 bits e 1 stop bit; o caminho
recente lê um registrador de 16 bits e usa 2 stop bits. `MODBUS_CONFIG` declara
timeout 1 s, mas o cliente instancia 0,5 s. Os requisitos da raiz fixam versões,
enquanto `ihm_esp32/requirements.txt` usa mínimos abertos. O venv está rastreado
apesar de regras de ignore: não deve ser copiado/ativado como ambiente portátil.

O uso de `asyncio.to_thread` exige Python >=3.9. Compatibilidade completa com OS,
firmware, arquitetura e bibliotecas não foi validada em ARM. A decisão sobre
atualização deve aguardar o inventário real e uma instalação isolada equivalente.

## Achados prioritários

| ID / prioridade | Camada e conclusão | Evidência e consequência |
|---|---|---|
| A01 / P1 | Backend: mudança pode sumir do delta WebSocket. **Reproduzido isoladamente.** | `main_server.py:771` calcula delta; `:794` aguarda envio; `:808` fotografa novamente o estado. Mudança ocorrida durante envio entra na referência sem ter sido transmitida. O heartbeat não reenvia necessariamente o campo omitido. |
| A02 / P1 | Backend: tarefa de broadcast pode terminar com mudança no conjunto de clientes. **Reproduzido isoladamente.** | Iteração de `self.clients` em `main_server.py:792` contém `await`; handler adiciona/remove clientes em `:120/:150`. `RuntimeError: Set changed size during iteration` sai do loop. Não há supervisão/recriação dessa task em `start/run`. |
| A03 / P0 para aceitação da máquina | Modbus/Ladder: “ângulo confirmado” não comprova setpoint usado na parada. **Confirmado no código e no teste isolado.** | `modbus_map.py:243` e `:248` usam o mesmo endereço para leitura/escrita. `modbus_client.py:839` relê esse endereço e o frontend recebe `verified=success` em `main_server.py:221`. O teste de 140° registra 280 em 0x0A00 e o relê; nenhum registrador de trabalho do Ladder é verificado. |
| A04 / P1 | Backend: estado do encoder pode permanecer antigo com timestamp/counter avançando. **Reproduzido isoladamente.** | `state_manager.py:513` incrementa contador/data antes das leituras; `:522` ignora retorno de `read_encoder`; falha retorna False sem invalidar o valor antigo (`:180–215`). Logo, contador e flag de conexão não medem leituras válidas. |
| A05 / P1 | Backend: escrita/verificação bloqueia o event loop. **Confirmado no código; duração real não medida.** | `main_server.py:206` chama método síncrono, que usa I/O bloqueante e `time.sleep` em `modbus_client.py:830/:836/:844/:857`. Pode atrasar WS/HTTP e watchdog. Não prova causa da falha de parada. |
| A06 / P1 | Comunicação: cliente compartilhado entre `to_thread` e handlers síncronos. **Risco, não colisão comprovada.** | Não há serialização de uma transação lógica completa no wrapper. A pymodbus 3.7.4 versionada tem `RLock` por transação; isso impede afirmar que toda chamada colide, mas não prova atomicidade de escrita+espera+verificação/reconexão. |
| A07 / P1 | Encoder/setpoints: escalas e endereços históricos conflitantes. **Confirmado no código/documentação; escala física desconhecida.** | Encoder: `(raw % 400) / 400 * 360 / 2`, `state_manager.py:188`. Setpoint: `int(graus*2)`, `modbus_map.py:534`. Diferença de unidades pode ser legítima ou incorreta conforme Ladder. Não converter automaticamente para pulsos ou trocar registradores. |
| A08 / P1 | Interface de segurança pode omitir estado real do pedal. **Confirmado no código, efeito no CLP não confirmado.** | `state_manager.py:629` força `pedal_segura=False` na projeção enviada. Isso não prova que uma proteção física foi desativada, mas a tela não é evidência fiel desse estado. Não alterado nesta entrega. |
| A09 / P2 | Plataforma: início automático e ambiente não rastreados de forma unívoca. **Confirmado no repositório.** | Serviços, paths e requirements divergentes; ausência de manifesto da instalação/imagem. Coletar versão por camada antes de qualquer upgrade/deploy. |

Arquivos referenciados acima são de [ihm_esp32](../../ihm_esp32). Reproduções:
[test_runtime_evidence.py](../../diagnostics/tests/test_runtime_evidence.py).
Os testes passam quando reproduzem a deficiência atual: não constituem correções.

### Limite de dobra: investigação própria

Em variantes arquivadas, [ladder_extract/ROT4.lad](../../ladder_extract/ROT4.lad)
contém MOV 0x0842→0x0942 (linha 338) e 0x0846→0x0944 (395), e
[Principal.lad](../../ladder_extract/Principal.lad) compara 0x04D6 com 0x0944
(304) e 0x0942 (403). Isso demonstra um caminho diferente do simples eco em
0x0A00, mas **não identifica o programa residente** nem valida a interpretação
completa dos contatos, escalas e funções desse Ladder.

Separar três evidências: valor solicitado; valor aceito na comunicação; valor
consumido pelo programa que determina a parada. Conferir também direção,
seleção da dobra, zero/referência, sensor, escala, saída de comando e inércia.
O módulo de polling recente não implementa uma parada segura por comparação de
ângulo; observação e log de dobra não equivalem a controle de segurança.

O módulo de encoder aplica `%400`, de modo que raw=399 exibe 179,55° e raw=400
exibe 0°. Pode mascarar acumulação/voltas ou ausência de referência; preservar
raw nos registros é essencial. A relação mecânica 2:1 continua hipótese a medir.

### Congelamento da interface: investigação própria

Correlacionar: instante de leitura válida → estado do backend → envio WS →
recepção no notebook → atualização DOM. As falhas A01/A02/A04/A05 podem afetar
essa cadeia. Uma conexão WS viva, heartbeat ou `last_update` recente não
comprovam que o encoder foi lido. Uma leitura constante pode significar máquina
parada. Medir antes de associar esse sintoma à falha de parada.

## Hardware, Linux e rede: situação atual

Não foi confirmado superaquecimento, subtensão, erro de SD, reinício inesperado,
conflito de IP ou defeito no chip Wi-Fi. O coletor prepara as evidências para essas
hipóteses; logs podem não persistir entre boots. `get_throttled` apresenta flags
atuais e de ocorrência, não uma cronologia confiável de falhas antigas.
Ausência de flags não certifica a fonte. Ver documentação de
[vcgencmd](https://www.raspberrypi.com/documentation/computers/os.html#vcgencmd).

“Connection refused” relatado na porta 22 indica rejeição TCP observada pelo
cliente, compatível com ausência de listener ou rejeição por firewall. Não é
erro de senha e não prova defeito de Wi-Fi. Identificar IP/MAC/serviço antes de
concluir. As alternativas de acesso estão no [roteiro de campo](COLETA_EM_CAMPO.md).

A documentação da [pymodbus sobre clientes](https://github.com/pymodbus-dev/pymodbus/blob/dev/doc/source/client.rst)
orienta serializar o acesso ao cliente. O código exato da versão instalada deve
ser examinado antes de escolher lock, fila ou cliente assíncrono.

## Fases e próximo marco

| Fase | Entrega/situação |
|---|---|
| 1 — clonar e auditar | Concluída para a base acima; execução da máquina preservada |
| 2 — arquitetura/versões | Inventário do repositório concluído; hardware/OS instalado pendentes |
| 3 — scripts seguros | Implementados coletor Linux, teste Windows, análise offline Modbus, painel e artefatos |
| 4 — instalação real | Pendente: notebook fora da rede; coleta e comparação preparadas |
| 5 — problemas e prioridades | Relatório atual separa código comprovado, reproduções e hipóteses |
| 6 — refatoração | Plano abaixo; não aplicada ao controle antes da coleta |
| 7 — imagem reproduzível | Adiada por solicitação; nenhuma imagem gerada |
| 8 — bancada/máquina | Roteiro preparado; movimento exige autorização e acompanhamento |

Sequência proposta de mudanças posteriores, em commits separados após a coleta:

1. Fixar baseline por hash/manifesto, capturar estado e contratos WS existentes.
2. Corrigir broadcast com snapshot consistente, coleção estável de clientes,
   timeout por cliente e supervisão; transformar reproduções em regressões.
3. Instrumentar tempo monotônico, sucesso/erro e idade por leitura no único dono
   do cliente Modbus, com memória/logs limitados. Nunca criar segundo mestre.
4. Serializar operações e retirar I/O síncrono do event loop, com contrato público
   preservado e falhas/reconexões testadas em bancada.
5. Somente após identificar Ladder/escala: definir o significado de “confirmado”,
   comparar registradores de trabalho e submeter mudanças de acionamento/Ladder
   à aprovação específica. Não corrigir o limite por tentativa de endereço.
6. Separar leitura de manutenção dos comandos, validar ambiente ARM reproduzível,
   procedimento de atualização da aplicação e rollback; só então considerar imagem.
