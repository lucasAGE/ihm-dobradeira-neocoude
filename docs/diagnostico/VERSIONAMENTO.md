# Versionamento em camadas e recuperação

Cada entrega terá um manifesto independente da imagem do SD. O comando
`diagnostics/artifacts.py inventory` prepara as seis camadas e mantém campos
não coletados explícitos. Versão do kit de manutenção: **0.3.0**. Ela não muda
nem representa a versão instalada na máquina. A entrega 0.3.0 inclui também
três arquivos corrigidos da aplicação, ainda não implantados, conforme
[CORRECAO_FEEDBACK.md](CORRECAO_FEEDBACK.md).

| Camada | Identidade mínima | Condição para atualização |
|---|---|---|
| 1. Linux/firmware | OS release, arquitetura, kernel, firmware, fonte de imagem base e checksum | Compatibilidade e boot validados no modelo físico identificado |
| 2. Hardware/rede/serviços | Revisão/configuração UART, conversor, AP/DHCP/rotas, unidades systemd e hashes | Comparação com instalação, acesso de recuperação e backup de configuração |
| 3. Python/dependências | Versão/arquitetura do interpretador, inventário real, lock e hashes dos pacotes futuros | Ambiente isolado em ARM; não resolver novos mínimos abertos no equipamento |
| 4. Aplicação | Versão/tag, commit completo, estado dirty e hashes dos arquivos | Contratos preservados, testes, artefato novo e rollback preparado |
| 5. Modbus/Ladder | Versão/hash do mapa, exportação/hash do Ladder residente, escalas/endereços | Compatibilidade demonstrada, aprovação específica para acionamento/Ladder |
| 6. Imagem do SD | Versão, data UTC, commit/manifesto das camadas 1–5, configurações e SHA-256 | Somente depois de validação; não gerada nesta etapa |

Manifesto de repositório sem coleta do alvo não deve receber modelo de placa,
Linux, firmware ou Ladder presumidos. Metadados do venv rastreado são evidência
histórica, não inventário atual. Hashes comparam bytes; CRLF/LF pode explicar uma
diferença, que deve ser investigada antes de concluir adulteração. O estado dirty
e os hashes importam mesmo quando o commit é igual.

## Atualizar só a aplicação, futuramente

Para a correção de feedback 0.3.0, usar o
[roteiro de campo](ATUALIZACAO_EM_CAMPO.md). Ele compara a base, faz backup e
restauração de teste e substitui somente três arquivos com o serviço parado,
preservando unidade/venv e recuperando dono/grupo/modo originais. Essa sequência
específica não serve para uma variante diferente da aplicação.

Preparar releases em diretórios distintos, mantendo o release anterior, ambiente
Python validado, dados mutáveis e configuração separados. Empacotar a aplicação
sem venv de outra máquina nem credenciais. A coleta inicial estabelecerá quais
arquivos e dados realmente pertencem à instalação; a seleção do backup no guia
é um exemplo, não descoberta automática de tudo que roda em produção.

Durante janela acordada e máquina em condição segura: verificar checksum e
compatibilidade do manifesto; preservar backup; instalar release candidato em
novo diretório; comparar configuração; executar validações de bancada; só depois
apontar o serviço para o candidato e reiniciar sob acompanhamento. A mudança de
serviço e o restart não são executados pelo kit. Não fazer `git pull` seguido de
upgrade de dependências automaticamente na instalação em produção.

Rollback: conservar release, ambiente e configuração anteriores; registrar hashes
e unidade anterior; retornar a eles em janela segura, após avaliar efeitos sobre
dados de produção. Uma versão diferente de Ladder pode impedir rollback apenas
do Python. Não assumir que restaurar a IHM restaura o CLP ou proteções.

## Backup fornecido nesta etapa

`backup` cria ZIP novo com arquivos explicitamente selecionados, manifesto
interno (versão, data, commit, tamanho, SHA-256 e modo de cada arquivo) e retorna
SHA-256 do arquivo final. `verify` recalcula hashes e confere conjunto completo.
`restore-staging` valida paths, tipo, tamanho e conteúdo antes de extrair em uma
pasta nova; recusa sobrescrita, links simbólicos, travessia e entradas duplicadas.
Não extrai diretamente sobre a instalação nem aplica serviços. Modos de arquivo
restaurados são restritos ao proprietário, sem setuid/setgid; revisar permissões
de serviço antes de eventual deploy.

Limites de seleção: 5.000 arquivos/200 MiB. Diretórios de ambiente, Git, cache e
saídas locais são excluídos. Backup de arquivos em alteração não é snapshot
consistente; coordenar a parada de escrita de dados mutáveis. Falha durante
empacotamento pode deixar arquivo parcial: o verificador deve rejeitá-lo; preserve
a evidência e use outro nome na próxima tentativa. Configurações explícitas
podem incluir segredos; o backup é privado, ao contrário de logs parcialmente
redigidos. Arquivos de dados/configuração externos ao diretório escolhido exigem
backup separado com sua própria raiz/seleção.

## Preservar e recuperar o cartão

A imagem integral do cartão atual exige procedimento offline em computador de
manutenção: identificar inequivocamente a mídia, desligamento coordenado, leitor
apropriado e destino de capacidade suficiente. Manter original intacto; registrar
capacidade/partições, data, checksum e manifesto; verificar uma cópia restaurada
em **outro cartão** e bancada. Não iniciar o cartão copiado na máquina sem avaliar
auto-start e estado seguro. Não há script de clonagem/gravação de SD nesta entrega.

Uma imagem já existente pode receber hash no notebook, sem ser alterada:

```bash
python diagnostics/artifacts.py inventory --root ihm_esp32 --label imagem-existente-v1 --snapshot coleta-real.json --ladder exportacao-residente.sup --image copia-existente.img --output imagem-existente-manifest.json
```

Usar `--image` só no computador de manutenção; leitura integral de imagem grande
não pertence à coleta leve no Raspberry. SHA-256 detecta alteração/corrupção, não
certifica autenticidade, boot, Ladder residente ou segurança do equipamento.

## Imagem reproduzível — etapa posterior

Após validar as camadas: fixar imagem oficial base e checksum; aplicar configurações
declaradas; construir ambiente Python com versões/hashes validados; instalar
release por commit; provisionar credenciais fora do repositório; gerar manifesto
e checksum final; registrar teste de boot/rede/serviço/Modbus em bancada e rollback.
Não tratar uma cópia artesanal do SD como construção reproduzível. Nenhuma etapa
de geração ou gravação foi executada nesta entrega.
