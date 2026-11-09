# Coleta em campo, sem movimento

Para identificar a versão, fazer backup, aplicar a correção de feedback e testar
pela rede, seguir [ATUALIZACAO_EM_CAMPO.md](ATUALIZACAO_EM_CAMPO.md). Este documento
permanece como referência de coleta inicial e acesso alternativo.

## Preparação e sequência

1. Identificar a máquina, responsável, condição operacional e janela de manutenção.
   Registrar hora/fuso de notebook e Raspberry, sem ajustar relógios automaticamente.
2. Executar o teste Windows na rede `IHM_NEOCOUDE`. Não varrer a rede inteira.
   Guardar IP do notebook, gateway, vizinhança ARP e respostas de cada serviço.
3. Abrir terminal local/SSH existente e coletar Linux uma vez. Descobrir primeiro
   unidade/ExecStart/usuário/grupos; repetir com `--app-root` e `--python` corretos.
4. Copiar relatórios ao notebook, calcular inventário comparativo e importar no
   painel. Não confundir coleta da bancada/WSL com dados do equipamento.
5. Registrar evidências faltantes e realizar inspeção física planejada. Nenhuma
   alteração de rede, serviço, Ladder, setpoint, saída ou proteção faz parte do kit.

## Quando SSH responde “Connection refused”

O teste Windows separa ping, abertura TCP, HTTP e handshake/recepção WS. Uma
porta aberta não garante o protocolo. Um timeout também pode ser filtragem,
rota incorreta ou serviço congestionado. Compare IP/MAC e tabela de vizinhos em
duas coletas; mudanças são indícios, não diagnóstico definitivo de IP duplicado.

Alternativas que preservam o cartão:

- **Monitor HDMI e teclado USB:** primeira opção para identificar modelo, Linux,
  serviços e logs usando a conta existente. Não instalar nem reiniciar a IHM.
- **Ethernet já configurada:** usar endereço conhecido da rede local ou consultar
  concessão no roteador administrado pelo responsável. Não mudar DHCP/AP para
  tentar “consertar” acesso sem antes salvar as configurações.
- **SSH desabilitado:** depois de coletar localmente, habilitação do serviço pela
  interface/raspi-config é uma alteração explícita de acesso remoto. Confirmar
  usuário e autenticação existentes e planejar com o responsável. O kit não faz isso.
- **Cartão em leitor:** desligamento coordenado e seguro antes de remover. Fazer
  cópia integral verificada em outra mídia e inspecionar partições em modo somente
  leitura. No Linux, ext4 pode exigir `ro,noload` para evitar replay do journal.
  Não aceitar sugestão de formatação do Windows nem executar reparo no original.
- **Arquivo `ssh` na partição de boot:** opção documentada para Raspberry Pi OS,
  após confirmar distribuição/versão e preservar backup. Requer escrita no boot
  e novo boot, portanto fica fora desta coleta somente leitura. Não recria
  credenciais e não é justificativa para regravar a imagem.
- **Console UART:** somente se já configurado e livre; não reutilizar UART do
  barramento industrial, nem ligar níveis RS-232/5 V aos GPIO. Avaliar com técnico
  a interface elétrica e isolamento antes de conectar instrumentos.

Referência de acesso e habilitação de SSH:
[Raspberry Pi — Remote access](https://www.raspberrypi.com/documentation/computers/remote-access.html#enable-the-ssh-server).
Não executar rotinas de primeira inicialização ou Raspberry Pi Imager no cartão existente.

## O que software permite verificar

| Camada | Dados preparados | Limitação / verificação adicional |
|---|---|---|
| Placa/CPU/RAM | Device Tree, arquitetura, lscpu, memória | Conferir identificação física da placa e revisão |
| Alimentação | Flags de subtensão, logs de kernel e boot anterior | Logs podem ter sido perdidos; medir 5 V no ponto de alimentação, queda nos cabos e comportamento do DC-DC |
| Temperatura/clock | thermal zone, frequência, flags | Amostra sem carga não prova margem térmica em produção |
| SD | Espaço, inodes, montagens RO/RW, logs mmc/I/O/ext4, atividade de disco | Não mede desgaste/integridade completa nem desempenho máximo; testar cópia offline quando necessário |
| Reinícios | boot ID, uptime, journal de boots e `last -x` | Fim abrupto de log é indício, não prova única de falha da fonte |
| Wi-Fi | Interfaces, chip/driver por USB/módulos, modo AP, stations, rfkill, logs | `iw link` pode dizer desconectado em AP; RSSI dos clientes vem de station dump quando suportado |
| DHCP/rede | Concessões, endereços, rotas, listeners, vizinhos | Uma fotografia não exclui conflito IP ou quedas intermitentes |
| Serviços | Unidade, usuário, ExecStart, estado, NRestarts, falhas | NRestarts não é histórico permanente de toda a vida do dispositivo |
| UART/USB | Metadados, symlinks, grupos, fuser, configuração de boot | Coletores não abrem tty nem alteram baud rate; visibilidade de processos depende das permissões |
| Modbus | Estado informado via WS; CRC/latência/erros em captura fornecida | Não prova cabeamento, isolamento ou coerência do setpoint de parada |

Não executar `fsck` em sistema montado, `badblocks`, `fio`, stress térmico, benchmark
de escrita, varredura de baud/slave ou reboot para “testar” durante operação.
Espaço livre e ausência de logs de erro não certificam o cartão.

## Inspeção física a registrar

Alimentação: documentar modelo/capacidade do conversor, aterramento, cabos,
conectores, fusíveis e aquecimento. Medição por profissional habilitado, com
procedimento de isolamento e instrumentos adequados. Multímetro pode não capturar
transientes rápidos; osciloscópio com técnica/isolamento apropriados pode ser
necessário. `vcgencmd measure_volts core` não mede os 5 V de entrada da placa.

RS-485: documentar topologia, comprimento/derivações, referência comum, isolamento
do conversor, blindagem e proximidade de inversor/contatores. Verificar polaridade
conforme os manuais dos dispositivos: rótulos A/B nem sempre são consistentes entre
fabricantes. Avaliar terminações nas extremidades e polarização prevista no
projeto. Medir resistências/continuidade apenas com circuito desenergizado e
seguro; não acrescentar resistores, inverter fios ou remover aterramento em tentativa.
Para ruído/reflexos, usar instrumentação diferencial/isolada compatível.

Referência: [Modbus — especificações e guia serial V1.02](https://www.modbus.org/modbus-specifications).
Aplicar o guia junto aos manuais do CLP/conversor e ao projeto elétrico real.

## Roteiro de bancada e aceitação

| Etapa | Condição / evidência esperada | Estado nesta entrega |
|---|---|---|
| Kit offline | Simuladores de HTTP/WS, captura conhecida, falhas, arquivo inválido, backup corrompido | Validado localmente; ver VALIDACAO.md |
| Baseline real sem movimento | Identidade da placa, versão/commit/hash, serviços e UART, OS/firmware, fonte/SD | Não executado |
| Observação passiva | Contadores de sucesso/erro, timestamps de leitura/envio/recepção, captura já existente | Não executado no alvo |
| Compatibilidade Ladder | Backup/exportação do residente, checksum e caminho setpoint→comparação→saída | Não executado; não escrever no CLP |
| Refatoração em bancada isolada | Contratos WS e Modbus, cliente lento, desconexões, reinícios, concorrência, rollback | Planejada após baseline |
| Teste com movimento | Autorização explícita, responsável presente, área controlada, proteções verificadas, plano de parada | Não autorizado nem executado |

O teste com movimento deve ter plano específico acordado antes: sequência e
sentido, referência/zero, ângulo solicitado/consumido/medido, repetibilidade,
sobrecorrida, perda de comunicação e resposta das proteções. Não há comandos nem
valores de acionamento automatizados neste roteiro. A simples indicação 140° na
tela ou eco de registrador não aprova o limite.

Ficha mínima por verificação: `id`, equipamento, data/fuso, operador, versões,
condição, método, arquivos/SHA-256, resultado observado, status
`não_executado|inconclusivo|falha|aprovado`, critério de aceitação e responsável.
Uma falha deve ter sua camada identificada; não atribuir automaticamente falta
de parada a congelamento de navegador ou à fonte sem correlação.
