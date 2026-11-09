# Ficha de atualização e feedback — Neocoude

Copiar para a pasta do atendimento e preencher. Não registrar senhas.

| Identificação | Valor observado |
|---|---|
| Data/hora/fuso e responsável | |
| Máquina, modelo Raspberry e hostname | |
| IP, usuário de acesso e unidade systemd | |
| Diretório real, Python/venv, usuário/grupo do serviço | |
| PID/ExecStart antes; modo LIVE ou STUB | |
| Commit informado e `source_state`/hashes antes | |
| Pacote candidato e SHA-256 conferido | |
| Backup: local no Raspberry, local no notebook e SHA-256 | |
| Permissões originais (`versao-parada.json`) e unidade salva | |
| Resultado da verificação/restauração de teste do backup | |
| Hashes depois, PID novo e tela servida | |
| `feedback_version` e `feedback_session` | |
| `NRestarts` no começo/fim da observação | |
| Coleta JSON, início/fim/duração e silêncio/gaps | |

| Sinal/grupo | Qualidade e valor inicial | Valor final / sucessos / erros novos | Método/condição | Resultado |
|---|---|---|---|---|
| Encoder bruto, pulsos e ângulos | | | Observação sem movimento | |
| Encoder: variação física/referência | | | Procedimento de manutenção/bancada | Pendente |
| E0 — zero | | | | |
| E1 — reserva/carenagem no mapa | | | | |
| E2 — pedal avanço | | | | |
| E3 — pedal parada | | | | |
| E4 — pedal recuo | | | | |
| E5 — segurança/carenagem NF | | | | |
| E6 — emergência NF | | | | |
| E7 — reserva | | | | |
| S0–S7 — bits de saída | | | Sem inferir atuação física | |
| Bits de controle/modos | | | | |
| Estados individuais e estado agregado | | | | |
| Ângulos programados/alvo, dobra, peças, RPM estimado | | | | |
| Falha já presente ou simulação em bancada isolada | | | Não provocar falha em produção | |
| Recuperação de leitura | | | | |

Resultados possíveis: **aprovado no escopo observado**, **inconclusivo**, **falha**
ou **pendente**. Bit 0/1 não determina polaridade elétrica sem circuito e Ladder.

| Fechamento | Registro |
|---|---|
| Resultado do feedback e evidências anexadas | |
| Testes físicos/dinâmicos pendentes | |
| Houve rollback? Motivo, arquivos restaurados e resultado | |
| Estado final do serviço e da máquina | |
| Responsável pela conclusão | |

Esta ficha registra atualização de software e feedback. Não é aprovação de
calibração, limite angular, proteções ou liberação para produção.
