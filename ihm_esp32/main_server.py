"""
Main Server - Servidor WebSocket IHM Web (Novo Ladder)
======================================================

Servidor principal que coordena:
- Modbus client (comunicação com CLP)
- State manager (estado da máquina - 8 estados)
- WebSocket server (comunicação com tablet)
- HTTP server (serve index.html)

Referência: PROJETO_LADDER_NOVO.md
"""

import asyncio
import websockets
import json
import argparse
import time
from pathlib import Path
from typing import Set
from aiohttp import web

from modbus_client import ModbusClientWrapper
from state_manager import MachineStateManager
from wifi_manager import get_wifi_manager
import modbus_map as mm


class IHMServer:
    """
    Servidor principal da IHM Web
    """
    
    def __init__(self, stub_mode: bool = False, port: str = '/dev/ttyUSB0'):
        """
        Inicializa servidor
        
        Args:
            stub_mode: True para modo simulado
            port: Porta serial para modo live
        """
        self.stub_mode = stub_mode
        self.port = port
        
        # Clientes WebSocket conectados
        self.clients: Set[websockets.WebSocketServerProtocol] = set()
        
        # Componentes principais
        self.modbus_client = None
        self.state_manager = None
        self.wifi_manager = None

        # Tasks asyncio
        self.tasks = []
        
    async def start(self):
        """Inicializa todos os componentes"""
        print("=" * 60)
        print("IHM WEB - DOBRADEIRA NEOCOUDE-HD-15")
        print("=" * 60)
        
        # 1. Inicializa Modbus client
        print(f"\nModo: {'STUB (simulação)' if self.stub_mode else 'LIVE (CLP real)'}")
        self.modbus_client = ModbusClientWrapper(
            stub_mode=self.stub_mode,
            port=self.port
        )
        
        if not self.modbus_client.connected:
            print("⚠️  AVISO: Modbus não conectado!")
            if not self.stub_mode:
                print("  Verifique:")
                print(f"  - Cabo RS485 conectado em {self.port}")
                print("  - CLP ligado e em RUN")
                print("  - Estado 00BE (190) ativo no ladder")
                print("\n  ⚙️  Servidor continuará rodando - CLP pode conectar depois")

        # 2. Inicializa State Manager (funciona mesmo sem CLP)
        self.state_manager = MachineStateManager(self.modbus_client)

        # NOVO 08/Fev/2026: Callback para auditoria de dobras
        # Quando uma dobra é completada, envia resultado para todos os clientes
        self.state_manager.on_bend_logged = self._on_bend_logged

        # 3. Inicia loop de polling
        poll_task = asyncio.create_task(self.state_manager.start_polling())
        self.tasks.append(poll_task)
        
        # 4. Inicia loop de broadcast
        broadcast_task = asyncio.create_task(self.broadcast_loop())
        self.tasks.append(broadcast_task)

        # 5. Inicializa WiFi Manager
        self.wifi_manager = get_wifi_manager()
        wifi_status = self.wifi_manager.get_status()
        if wifi_status['dongle_detected']:
            print(f"📶 Dongle WiFi USB detectado: {self.wifi_manager.DONGLE_INTERFACE}")
            # Inicia loop de auto-connect
            wifi_task = asyncio.create_task(self.wifi_manager.auto_connect_loop())
            self.tasks.append(wifi_task)
        else:
            print("📶 Dongle WiFi USB não detectado (conecte para habilitar internet)")

        print("\n✓ Servidor iniciado com sucesso")
        print(f"  WebSocket: ws://localhost:8765")
        print(f"  HTTP: http://localhost:8080")
        print("\nAbra http://localhost:8080 no navegador do tablet")
        print("Pressione Ctrl+C para encerrar\n")
        
        return True
        
    async def handle_websocket(self, websocket):
        """
        Gerencia conexão WebSocket de um cliente

        Args:
            websocket: Conexão WebSocket
        """
        # Registra cliente
        self.clients.add(websocket)
        client_addr = websocket.remote_address
        print(f"🔗 Cliente WebSocket conectado: {client_addr}")
        
        try:
            # Envia estado completo inicial
            initial_state = self.state_manager.get_state()
            print(f"🔍 [DEBUG] Estado completo antes de enviar: {len(initial_state)} chaves")
            print(f"🔍 [DEBUG] modbus_connected no estado: {initial_state.get('modbus_connected')}")
            print(f"🔍 [DEBUG] connected no estado: {initial_state.get('connected')}")
            print(f"🔍 [DEBUG] encoder_raw no estado: {initial_state.get('encoder_raw')}")
            print(f"🔍 [DEBUG] encoder_degrees no estado: {initial_state.get('encoder_degrees')}")
            print(f"🔍 [DEBUG] angles no estado: {initial_state.get('angles')}")
            print(f"🔍 [DEBUG] velocidade_rpm no estado: {initial_state.get('velocidade_rpm')}")
            print(f"🔍 [DEBUG] target_angle no estado: {initial_state.get('target_angle')}")

            await websocket.send(json.dumps({
                'type': 'full_state',
                'data': initial_state
            }))
            print("✅ [DEBUG] Estado completo enviado com sucesso!")
            
            # Loop de recebimento de comandos
            async for message in websocket:
                await self.handle_client_message(websocket, message)
                
        except websockets.exceptions.ConnectionClosed:
            print(f"✗ Cliente desconectado: {client_addr}")
        finally:
            # Remove cliente
            self.clients.discard(websocket)
            
    async def handle_client_message(self, websocket, message: str):
        """
        Processa mensagem recebida do cliente

        Args:
            websocket: Conexão WebSocket
            message: Mensagem JSON
        """
        try:
            data = json.loads(message)
            action = data.get('action')
            print(f"📨 Comando recebido: {action} - {data}")  # LOG ADICIONAL

            if action == 'press_key':
                # Pressionar botão
                key_name = data.get('key')  # Ex: 'K1', 'S1', 'ENTER'
                
                # Mapeia nome para endereço
                addr = None
                if key_name in mm.KEYBOARD_NUMERIC:
                    addr = mm.KEYBOARD_NUMERIC[key_name]
                elif key_name in mm.KEYBOARD_FUNCTION:
                    addr = mm.KEYBOARD_FUNCTION[key_name]
                    
                if addr:
                    success = self.modbus_client.press_key(addr)
                    await websocket.send(json.dumps({
                        'type': 'key_response',
                        'key': key_name,
                        'success': success
                    }))
                    
            elif action == 'change_speed':
                # DEPRECATED 16/Nov/2025: K1+K7 via Modbus não funciona!
                # Usar action='write_speed' com valor específico (5, 10, 15)
                await websocket.send(json.dumps({
                    'type': 'error',
                    'message': 'DEPRECATED: Use write_speed com valor específico (5, 10 ou 15 RPM)'
                }))
                
            elif action == 'toggle_mode':
                # Toggle direto do modo (bypass S1+E6)
                await self.handle_toggle_mode(websocket, data)

            elif action == 'write_angle':
                # Escrever ângulo de dobra
                # MELHORADO 08/Fev/2026: Verificação de escrita + leitura forçada + broadcast
                bend_num = data.get('bend')  # 1, 2 ou 3
                angle_degrees = float(data.get('angle'))  # Graus (ex: 90.0, 120.5)

                print(f"📝 [WEB] Recebido: Gravar Dobra {bend_num} = {angle_degrees}°")

                if bend_num in [1, 2, 3]:
                    # Usa método com verificação (read-after-write)
                    success = self.modbus_client.write_bend_angle(bend_num, angle_degrees, verify=True)

                    # NOVO: Força leitura imediata dos ângulos no próximo ciclo de polling
                    if success:
                        self.state_manager.force_angle_read = True

                    status_icon = '✅' if success else '❌'
                    print(f"{status_icon} [WEB] Dobra {bend_num} = {angle_degrees}° → {'CONFIRMADO' if success else 'FALHOU'}")

                    # Resposta detalhada ao cliente
                    response = {
                        'type': 'angle_response',
                        'bend': bend_num,
                        'angle': angle_degrees,
                        'success': success,
                        'verified': success,  # Indica que foi verificado
                        'message': f'Ângulo {bend_num} {"confirmado" if success else "FALHOU - verifique conexão"}',
                    }

                    await websocket.send(json.dumps(response))

                    # BROADCAST para TODOS os clientes
                    if success:
                        # Atualiza estado local imediatamente (sem esperar polling)
                        bend_key = f'bend_{bend_num}'
                        self.state_manager.machine_state['angles'][bend_key] = angle_degrees

                        # Broadcast imediato com status de confirmação
                        update_msg = json.dumps({
                            'type': 'state_update',
                            'data': {
                                'angles': {bend_key: angle_degrees},
                                f'bend_{bend_num}_left': angle_degrees,
                                'target_angle': angle_degrees if self.state_manager.machine_state.get('dobra_atual', 1) == bend_num else self.state_manager.machine_state.get('target_angle', 0),
                                'angle_confirmed': {
                                    'bend': bend_num,
                                    'angle': angle_degrees,
                                    'timestamp': time.time()
                                }
                            }
                        })
                        for client in self.clients:
                            try:
                                await client.send(update_msg)
                            except:
                                pass
                        print(f"📢 [BROADCAST] Ângulo {bend_num} = {angle_degrees}° CONFIRMADO para {len(self.clients)} clientes")
                    else:
                        # Erro: notifica todos os clientes
                        error_msg = json.dumps({
                            'type': 'angle_error',
                            'bend': bend_num,
                            'angle': angle_degrees,
                            'message': 'Falha ao gravar ângulo - verifique conexão CLP'
                        })
                        for client in self.clients:
                            try:
                                await client.send(error_msg)
                            except:
                                pass
                        print(f"🚨 [BROADCAST] ERRO ao gravar ângulo {bend_num}")
                else:
                    print(f"❌ [WEB] Número de dobra inválido: {bend_num}")

            elif action == 'write_output':
                # Controlar saída digital (motor)
                output_name = data.get('output')  # 'S0' ou 'S1'
                value = data.get('value')  # True/False

                if output_name in mm.DIGITAL_OUTPUTS:
                    # M-002: INTERTRAVAMENTO S0/S1 (Safety)
                    if value and output_name in ['S0', 'S1']:
                        # Verificar se a outra saída está ativa
                        other_output = 'S1' if output_name == 'S0' else 'S0'
                        other_addr = mm.DIGITAL_OUTPUTS[other_output]
                        other_state = self.modbus_client.read_coil(other_addr)

                        if other_state:
                            # BLOQUEIO DE SEGURANÇA
                            print(f"⚠️ BLOQUEIO: {output_name} não pode ligar enquanto {other_output} está ativo!")
                            await websocket.send(json.dumps({
                                'type': 'error',
                                'message': f'ERRO DE SEGURANÇA: {other_output} ainda está ativo. Pare o motor antes de inverter direção.'
                            }))
                            return

                    addr = mm.DIGITAL_OUTPUTS[output_name]
                    success = self.modbus_client.write_coil(addr, value)
                    print(f"{'✓' if success else '✗'} Motor {output_name}: {'ON' if value else 'OFF'}")
                    await websocket.send(json.dumps({
                        'type': 'output_response',
                        'output': output_name,
                        'value': value,
                        'success': success
                    }))

            elif action == 'write_speed':
                # Alterar velocidade do motor (dimmer contínuo 0-15 RPM)
                # ATUALIZADO 27/Nov/2025: Suporte a valores contínuos 0-15 RPM
                speed = data.get('speed')  # RPM (0.0 a 15.0)

                try:
                    speed = float(speed)
                    if 0 <= speed <= mm.RPM_MAX:
                        # Converte RPM para valor do registro usando mm.rpm_to_register()
                        # CORRIGIDO 27/Nov/2025: Escreve em 0x0A06 (IHM -> Ladder copia para 0x06E0)
                        # Valores: 5 RPM=527, 10 RPM=1055, 15 RPM=1583, 19 RPM=2000 (max)
                        register_value = mm.rpm_to_register(speed)
                        success = self.modbus_client.write_register(mm.INVERTER['VELOCIDADE_WRITE'], register_value)
                        print(f"{'✓' if success else '✗'} Velocidade: {speed:.1f} RPM (reg={register_value} hex=0x{register_value:04X} -> 0x0A06)")
                        await websocket.send(json.dumps({
                            'type': 'speed_response',
                            'speed': speed,
                            'register_value': register_value,
                            'success': success
                        }))
                    else:
                        print(f"✗ Velocidade fora da faixa: {speed}")
                        await websocket.send(json.dumps({
                            'type': 'error',
                            'message': f'Velocidade fora da faixa: {speed}. Use 0 a {mm.RPM_MAX:.0f} RPM.'
                        }))
                except (ValueError, TypeError):
                    print(f"✗ Velocidade inválida: {speed}")
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': f'Velocidade inválida: {speed}. Use valor numérico 0-15.'
                    }))

            elif action == 'motor_control':
                # Controle de motor via coils descobertos no ladder
                # ✅ ADICIONADO 20/Nov/2025 - Usa coils 0x0190/0x0191
                command = data.get('command')

                if command == 'start_forward':
                    success = self.modbus_client.start_forward()
                    print(f"{'✓' if success else '✗'} Comando AVANÇAR enviado")
                    await websocket.send(json.dumps({
                        'type': 'motor_response',
                        'command': 'forward',
                        'success': success
                    }))

                elif command == 'start_backward':
                    success = self.modbus_client.start_backward()
                    print(f"{'✓' if success else '✗'} Comando RECUAR enviado")
                    await websocket.send(json.dumps({
                        'type': 'motor_response',
                        'command': 'backward',
                        'success': success
                    }))

                elif command == 'stop':
                    success = self.modbus_client.stop_motor()
                    print(f"{'✓' if success else '✗'} Comando PARAR enviado")
                    await websocket.send(json.dumps({
                        'type': 'motor_response',
                        'command': 'stop',
                        'success': success
                    }))

                else:
                    print(f"✗ Comando de motor inválido: {command}")
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': f'Comando inválido: {command}'
                    }))

            elif action == 'emergency_stop':
                # M-001: PARADA DE EMERGÊNCIA (NR-12)
                print("🚨 EMERGÊNCIA ACIONADA! Desligando tudo...")

                # Desliga S0 e S1 imediatamente (sem verificação)
                s0_success = self.modbus_client.write_coil(mm.DIGITAL_OUTPUTS['S0'], False)
                s1_success = self.modbus_client.write_coil(mm.DIGITAL_OUTPUTS['S1'], False)

                # Opcional: Zera velocidade (ou coloca em classe mais baixa)
                # speed_success = self.modbus_client.write_register(mm.SUPERVISION_AREA['SPEED_CLASS'], 5)

                print(f"{'✓' if s0_success and s1_success else '✗'} Motor desligado (S0={s0_success}, S1={s1_success})")

                await websocket.send(json.dumps({
                    'type': 'emergency_response',
                    'success': s0_success and s1_success,
                    'message': 'Parada de emergência executada'
                }))

            elif action == 'write_pedal_segura':
                # Toggle PEDAL_SEGURA (exige segurar pedal para motor girar)
                # NOVO 27/Nov/2025: Endereço 0x0384 (900 decimal)
                value = data.get('value')  # True/False

                if value is not None:
                    success = self.modbus_client.write_coil(mm.CONTROL_BITS['PEDAL_SEGURA'], bool(value))
                    status = "ATIVADO" if value else "DESATIVADO"
                    print(f"{'✓' if success else '✗'} PEDAL_SEGURA {status}")
                    await websocket.send(json.dumps({
                        'type': 'pedal_segura_response',
                        'value': value,
                        'success': success
                    }))
                else:
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': 'Valor de PEDAL_SEGURA não especificado'
                    }))

            elif action == 'set_manual_mode':
                # Ativa/desativa modo manual (estado 7 da máquina de estados)
                # NOVO 27/Nov/2025: Controla bit MODO_MANUAL (0x0383)
                value = data.get('value')  # True para ativar manual, False para auto

                if value is not None:
                    # Escreve no bit de controle MODO_MANUAL
                    manual_success = self.modbus_client.write_coil(mm.CONTROL_BITS['MODO_MANUAL'], bool(value))
                    # Também atualiza MODO_AUTO para garantir consistência
                    auto_success = self.modbus_client.write_coil(mm.CONTROL_BITS['MODO_AUTO'], not bool(value))

                    success = manual_success and auto_success
                    mode_name = "MANUAL" if value else "AUTOMÁTICO"
                    print(f"{'✓' if success else '✗'} Modo alterado para {mode_name}")

                    await websocket.send(json.dumps({
                        'type': 'mode_response',
                        'manual_mode': value,
                        'success': success
                    }))
                else:
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': 'Valor de modo não especificado'
                    }))

            elif action == 'reset_counter':
                # Zera contador de peças
                # NOVO 27/Nov/2025: Endereço 0x0920 (2336 decimal)
                success = self.modbus_client.write_register(mm.WORK_REGISTERS['CONTADOR_PECAS'], 0)
                print(f"{'✓' if success else '✗'} Contador de peças zerado")

                await websocket.send(json.dumps({
                    'type': 'counter_response',
                    'success': success,
                    'new_value': 0
                }))

            elif action == 'set_habilitado':
                # Habilita/desabilita máquina (bit HABILITADO)
                # NOVO 27/Nov/2025: Endereço 0x0387
                value = data.get('value')

                if value is not None:
                    success = self.modbus_client.write_coil(mm.CONTROL_BITS['HABILITADO'], bool(value))
                    status = "HABILITADA" if value else "DESABILITADA"
                    print(f"{'✓' if success else '✗'} Máquina {status}")
                    await websocket.send(json.dumps({
                        'type': 'habilitado_response',
                        'value': value,
                        'success': success
                    }))
                else:
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': 'Valor de HABILITADO não especificado'
                    }))

            # ========================================
            # AUTO-CALIBRACAO - DESATIVADO 02/Jan/2026
            # ========================================
            # Calibração manual via ajuste de ângulos (usuário compensa inércia)
            # Para reativar, descomentar este bloco e código em modbus_map.py/state_manager.py

            # elif action == 'calib_start':
            #     # Inicia processo de auto-calibração
            #     warmup = data.get('warmup', False)  # Flag de aquecimento hidráulico
            #
            #     # Verifica se está em IDLE
            #     state_idle = self.modbus_client.read_coil(mm.MACHINE_STATES['ST_IDLE'])
            #     if not state_idle:
            #         await websocket.send(json.dumps({
            #             'type': 'calib_response',
            #             'success': False,
            #             'message': 'Máquina deve estar em IDLE para iniciar calibração'
            #         }))
            #         print("❌ [Calib] Tentativa de iniciar calibração fora de IDLE")
            #         return
            #
            #     # Define flag de aquecimento
            #     warmup_success = self.modbus_client.write_coil(mm.CALIBRATION['FLAG_AQUECER'], bool(warmup))
            #     print(f"🔧 [Calib] Aquecimento: {'SIM' if warmup else 'NÃO'} (success={warmup_success})")
            #
            #     # Dispara comando de iniciar calibração
            #     start_success = self.modbus_client.write_coil(mm.CALIBRATION['CMD_INICIA_CALIB'], True)
            #
            #     # Aguarda um pouco e desliga o comando (pulso)
            #     await asyncio.sleep(0.2)
            #     self.modbus_client.write_coil(mm.CALIBRATION['CMD_INICIA_CALIB'], False)
            #
            #     success = warmup_success and start_success
            #     print(f"{'✅' if success else '❌'} [Calib] Calibração iniciada")
            #
            #     await websocket.send(json.dumps({
            #         'type': 'calib_response',
            #         'success': success,
            #         'message': 'Calibração iniciada!' if success else 'Falha ao iniciar calibração',
            #         'warmup': warmup
            #     }))
            #
            #     # Broadcast para todos os clientes
            #     if success:
            #         for client in self.clients:
            #             try:
            #                 await client.send(json.dumps({
            #                     'type': 'calib_started',
            #                     'warmup': warmup
            #                 }))
            #             except:
            #                 pass
            #
            # elif action == 'calib_abort':
            #     # Aborta processo de calibração (força ST_IDLE)
            #     print("⚠️ [Calib] Abortando calibração...")
            #
            #     # Força todos os estados de motor para OFF (segurança)
            #     self.modbus_client.write_coil(mm.DIGITAL_OUTPUTS['S0'], False)
            #     self.modbus_client.write_coil(mm.DIGITAL_OUTPUTS['S1'], False)
            #     self.modbus_client.write_coil(mm.DIGITAL_OUTPUTS['S2'], False)
            #
            #     # Reseta estado de calibração
            #     self.modbus_client.write_coil(mm.CALIBRATION['ST_CALIBRACAO'], False)
            #
            #     # Força volta para ST_IDLE
            #     # Primeiro desliga todos os outros estados
            #     for state_name, state_addr in mm.MACHINE_STATES.items():
            #         if state_name != 'ST_IDLE':
            #             self.modbus_client.write_coil(state_addr, False)
            #
            #     # Liga ST_IDLE
            #     success = self.modbus_client.write_coil(mm.MACHINE_STATES['ST_IDLE'], True)
            #
            #     # Zera etapa de calibração
            #     self.modbus_client.write_register(mm.CALIBRATION['ETAPA_CALIB'], 0)
            #
            #     print(f"{'✅' if success else '❌'} [Calib] Calibração abortada")
            #
            #     await websocket.send(json.dumps({
            #         'type': 'calib_aborted',
            #         'success': success
            #     }))
            #
            #     # Broadcast para todos os clientes
            #     for client in self.clients:
            #         try:
            #             await client.send(json.dumps({
            #                 'type': 'calib_aborted',
            #                 'success': success
            #             }))
            #         except:
            #             pass
            #
            # elif action == 'calib_status':
            #     # Retorna status atual da calibração
            #     calib_state = self.state_manager.machine_state.get('calibration', {})
            #     await websocket.send(json.dumps({
            #         'type': 'calib_status',
            #         'data': calib_state
            #     }))

            # ========================================
            # WIFI MANAGER ACTIONS (30/Nov/2025)
            # ========================================
            elif action == 'wifi_status':
                # Retorna status completo do WiFi (dongle, AP, IPs)
                wifi_status = self.wifi_manager.get_status()
                await websocket.send(json.dumps({
                    'type': 'wifi_status',
                    'data': wifi_status
                }))
                print(f"📶 [WiFi] Status enviado: dongle={wifi_status['dongle_detected']}, conectado={wifi_status['wifi_connected']}")

            elif action == 'wifi_scan':
                # Escaneia redes WiFi disponíveis
                print("📶 [WiFi] Escaneando redes...")
                networks = self.wifi_manager.scan_networks()
                await websocket.send(json.dumps({
                    'type': 'wifi_scan_result',
                    'networks': networks
                }))
                print(f"📶 [WiFi] {len(networks)} redes encontradas")

            elif action == 'wifi_connect':
                # Conecta na rede WiFi especificada
                ssid = data.get('ssid')
                password = data.get('password')

                if ssid and password:
                    print(f"📶 [WiFi] Conectando em '{ssid}'...")
                    await websocket.send(json.dumps({
                        'type': 'wifi_connecting',
                        'ssid': ssid
                    }))

                    # Executa conexão (pode demorar)
                    success, message = self.wifi_manager.connect_to_wifi(ssid, password)
                    await websocket.send(json.dumps({
                        'type': 'wifi_connect_result',
                        'success': success,
                        'message': message,
                        'ssid': ssid
                    }))
                    print(f"📶 [WiFi] Resultado: {message}")
                else:
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': 'SSID e senha são obrigatórios'
                    }))

            elif action == 'wifi_disconnect':
                # Desconecta do WiFi
                success, message = self.wifi_manager.disconnect_wifi()
                await websocket.send(json.dumps({
                    'type': 'wifi_disconnect_result',
                    'success': success,
                    'message': message
                }))
                print(f"📶 [WiFi] Desconectado: {message}")

            elif action == 'wifi_save_config':
                # Salva configuração de WiFi (SSID e senha)
                ssid = data.get('ssid')
                password = data.get('password')
                auto_connect = data.get('auto_connect', True)

                if ssid and password:
                    self.wifi_manager.set_config(ssid, password, auto_connect)
                    await websocket.send(json.dumps({
                        'type': 'wifi_config_saved',
                        'success': True,
                        'ssid': ssid
                    }))
                    print(f"📶 [WiFi] Config salva: SSID='{ssid}', auto_connect={auto_connect}")
                else:
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': 'SSID e senha são obrigatórios para salvar'
                    }))

            elif action == 'wifi_enable_nat':
                # Habilita NAT (compartilhamento de internet)
                success = self.wifi_manager.enable_nat()
                await websocket.send(json.dumps({
                    'type': 'wifi_nat_result',
                    'enabled': success
                }))
                print(f"📶 [WiFi] NAT {'habilitado' if success else 'falhou'}")

            elif action == 'wifi_disable_nat':
                # Desabilita NAT
                success = self.wifi_manager.disable_nat()
                await websocket.send(json.dumps({
                    'type': 'wifi_nat_result',
                    'enabled': not success
                }))
                print(f"📶 [WiFi] NAT {'desabilitado' if success else 'falhou ao desabilitar'}")

            elif action == 'get_bend_stats':
                # NOVO 08/Fev/2026: Retorna estatísticas de auditoria de dobras
                from bend_logger import get_bend_logger
                logger = get_bend_logger()

                stats = logger.get_session_stats()
                recommendations = logger.get_compensation_recommendation()
                trend = logger.get_error_trend()

                await websocket.send(json.dumps({
                    'type': 'bend_stats',
                    'stats': stats,
                    'recommendations': recommendations,
                    'trend': trend
                }))
                print(f"📊 [Stats] Enviadas estatísticas de dobras")

        except json.JSONDecodeError:
            print(f"✗ JSON inválido recebido: {message}")
        except Exception as e:
            print(f"✗ Erro processando mensagem: {e}")

    def _on_bend_logged(self, result: dict):
        """
        Callback chamado quando uma dobra é registrada pelo BendLogger.

        NOVO 08/Fev/2026: Sistema de auditoria de dobras.
        Faz broadcast do resultado para todos os clientes conectados.

        Args:
            result: Dicionário com resultado da dobra:
                - success: bool
                - error: float (graus de erro)
                - alert: str ou None
                - compensation_suggested: float
                - record: dict com todos os dados
        """
        # Prepara mensagem para broadcast
        message = {
            'type': 'bend_completed',
            'success': result.get('success', False),
            'error_degrees': result.get('error', 0.0),
            'alert': result.get('alert'),
            'compensation_suggested': result.get('compensation_suggested', 0.0),
            'record': result.get('record', {})
        }

        # Log
        if result.get('alert'):
            print(f"🚨 [AUDITORIA] {result['alert']}")
        else:
            print(f"✅ [AUDITORIA] Dobra OK (erro: {result.get('error', 0):.1f}°)")

        # Broadcast assíncrono para todos os clientes
        # Precisa agendar porque estamos em contexto síncrono
        asyncio.create_task(self._broadcast_bend_result(message))

    async def _broadcast_bend_result(self, message: dict):
        """Faz broadcast do resultado de uma dobra para todos os clientes."""
        if not self.clients:
            return

        msg_json = json.dumps(message)
        for client in self.clients:
            try:
                await client.send(msg_json)
            except Exception as e:
                print(f"⚠️ Erro enviando resultado de dobra: {e}")

        print(f"📢 [BROADCAST] Resultado de dobra enviado para {len(self.clients)} clientes")

    async def broadcast_loop(self):
        """
        Loop que envia atualizações para todos os clientes conectados

        OTIMIZADO 06/Jan/2026:
        - Broadcast a cada 150ms (balanceado)
        - Heartbeat a cada 3s (margem segura para watchdog 10s)
        - Logging de erros melhorado
        - Timestamp em cada mensagem
        """
        previous_state = {}
        heartbeat_counter = 0
        HEARTBEAT_INTERVAL = 20  # A cada 20 broadcasts (3s @ 150ms) - bem antes do watchdog!

        while True:
            await asyncio.sleep(0.15)  # OTIMIZADO 06/Jan/2026: Broadcast a cada 150ms

            if not self.clients:
                # Atualiza previous_state mesmo sem clientes
                previous_state = self.state_manager.get_state()
                heartbeat_counter = 0
                continue

            # Heartbeat periódico (a cada 3s)
            heartbeat_counter += 1
            send_heartbeat = (heartbeat_counter >= HEARTBEAT_INTERVAL)
            if send_heartbeat:
                heartbeat_counter = 0

            # Pega apenas mudanças (deltas)
            current_state = self.state_manager.get_state()
            changes = {key: value for key, value in current_state.items()
                       if key not in previous_state or previous_state[key] != value}

            # CRÍTICO: Envia heartbeat SEMPRE a cada 3s (keep-alive)
            if send_heartbeat:
                if not changes:
                    changes = {'heartbeat': True}
                else:
                    # Adiciona heartbeat junto com as mudanças
                    changes['heartbeat'] = True

            if changes:
                # Adiciona timestamp para debug
                changes['timestamp'] = time.time()

                message = json.dumps({
                    'type': 'state_update',
                    'data': changes
                })

                # Envia para todos os clientes
                disconnected = set()
                for client in tuple(self.clients):
                    try:
                        await client.send(message)
                    except websockets.exceptions.ConnectionClosed as e:
                        print(f"⚠️ Cliente desconectou durante broadcast: {client.remote_address} - {e}")
                        disconnected.add(client)
                    except Exception as e:
                        print(f"✗ Erro enviando para cliente {client.remote_address}: {e}")
                        disconnected.add(client)

                # Remove clientes desconectados
                if disconnected:
                    print(f"🔌 Removendo {len(disconnected)} cliente(s) desconectado(s)")
                    self.clients -= disconnected

            # Atualiza estado anterior
            previous_state = current_state
                
    async def handle_toggle_mode(self, websocket, data):
        """
        Handler para toggle de modo (MODO_AUTO/MODO_MANUAL via CONTROL_BITS)
        ATUALIZADO 27/Nov/2025: Usa novos endereços 0x0382/0x0383
        """
        print("🔄 Toggle de modo (via CONTROL_BITS)...")

        # Ler modo atual via control_bits
        modo_manual = self.modbus_client.read_coil(mm.CONTROL_BITS['MODO_MANUAL'])
        mode_antes = "MANUAL" if modo_manual else "AUTO" if modo_manual is not None else "UNKNOWN"

        if modo_manual is not None:
            # Toggle: se estava manual, vai para auto; se estava auto, vai para manual
            new_manual = not modo_manual

            # Escreve nos dois bits para garantir consistência
            success_manual = self.modbus_client.write_coil(mm.CONTROL_BITS['MODO_MANUAL'], new_manual)
            success_auto = self.modbus_client.write_coil(mm.CONTROL_BITS['MODO_AUTO'], not new_manual)
            success = success_manual and success_auto

            if success:
                mode_depois = "MANUAL" if new_manual else "AUTO"

                # Aguardar sincronização
                await asyncio.sleep(0.3)

                # Broadcast para TODOS os clientes
                update = {
                    'type': 'state_update',
                    'data': {
                        'mode_manual': new_manual,
                        'mode_text': mode_depois,
                        'control_bits': {
                            'MODO_MANUAL': new_manual,
                            'MODO_AUTO': not new_manual
                        }
                    }
                }

                for client in self.clients:
                    try:
                        await client.send(json.dumps(update))
                    except:
                        pass

                print(f"✅ Modo alterado: {mode_antes} → {mode_depois}")
            else:
                await websocket.send(json.dumps({
                    'type': 'error',
                    'message': 'Falha ao alternar modo - verifique conexão Modbus'
                }))
                print("❌ Falha ao alternar modo")
        else:
            await websocket.send(json.dumps({
                'type': 'error',
                'message': 'Falha ao ler modo atual - verifique conexão Modbus'
            }))
            print("❌ Falha ao ler modo atual")

    async def http_handler(self, request):
        """
        Serve arquivo index.html
        
        Args:
            request: Request HTTP
            
        Returns:
            Response com HTML
        """
        html_path = Path(__file__).parent / 'static' / 'index.html'

        if html_path.exists():
            return web.FileResponse(html_path)
        else:
            return web.Response(text="index.html não encontrado", status=404)

    async def captive_portal_android(self, request):
        """
        Responde para detecção de captive portal do Android
        URL: /generate_204
        Android espera HTTP 204 (No Content) quando NÃO há captive portal
        Retornamos HTTP 302 (redirect) para indicar que HÁ captive portal
        """
        return web.Response(
            status=302,
            headers={'Location': 'http://192.168.50.1:8080/'}
        )

    async def captive_portal_ios(self, request):
        """
        Responde para detecção de captive portal do iOS/macOS
        URL: /hotspot-detect.html
        Apple espera HTML com <title>Success</title> quando NÃO há captive portal
        Retornamos redirect para indicar que HÁ captive portal
        """
        return web.Response(
            status=302,
            headers={'Location': 'http://192.168.50.1:8080/'}
        )

    async def captive_portal_windows(self, request):
        """
        Responde para detecção de captive portal do Windows
        URL: /connecttest.txt
        Windows espera texto "Microsoft Connect Test" quando NÃO há captive portal
        Retornamos redirect para indicar que HÁ captive portal
        """
        return web.Response(
            status=302,
            headers={'Location': 'http://192.168.50.1:8080/'}
        )

    async def run(self):
        """Executa servidor (WebSocket + HTTP)"""
        # Inicializa componentes
        if not await self.start():
            return
            
        # Servidor HTTP (para servir index.html)
        app = web.Application()
        app.router.add_get('/', self.http_handler)
        app.router.add_get('/index.html', self.http_handler)
        app.router.add_static('/static', Path(__file__).parent / 'static')

        # ==========================================
        # CAPTIVE PORTAL - Detecção automática
        # ==========================================
        # Android
        app.router.add_get('/generate_204', self.captive_portal_android)
        app.router.add_get('/gen_204', self.captive_portal_android)

        # iOS/macOS
        app.router.add_get('/hotspot-detect.html', self.captive_portal_ios)
        app.router.add_get('/library/test/success.html', self.captive_portal_ios)

        # Windows
        app.router.add_get('/connecttest.txt', self.captive_portal_windows)
        app.router.add_get('/redirect', self.captive_portal_windows)
        app.router.add_get('/ncsi.txt', self.captive_portal_windows)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 8080)
        await site.start()

        # Servidor WebSocket
        print("🔌 Iniciando WebSocket server...")
        async with websockets.serve(self.handle_websocket, '0.0.0.0', 8765):
            print("✓ WebSocket server pronto na porta 8765")
            # Mantém rodando até Ctrl+C
            await asyncio.Future()  # Run forever
            
    def stop(self):
        """Encerra servidor"""
        print("\nEncerrando servidor...")

        if self.state_manager:
            self.state_manager.stop_polling()
            # BUGFIX: Aguardar um pouco para poll atual terminar (evita race condition)
            import time
            time.sleep(0.5)

        if self.modbus_client:
            self.modbus_client.close()

        for task in self.tasks:
            task.cancel()

        print("✓ Servidor encerrado")


async def main():
    """Função principal"""
    parser = argparse.ArgumentParser(description='IHM Web - Dobradeira NEOCOUDE-HD-15')
    parser.add_argument('--stub', action='store_true', help='Modo stub (simulação sem CLP)')
    parser.add_argument('--port', default='/dev/ttyUSB0', help='Porta serial (padrão: /dev/ttyUSB0)')
    
    args = parser.parse_args()
    
    server = IHMServer(stub_mode=args.stub, port=args.port)
    
    try:
        await server.run()
    except KeyboardInterrupt:
        print("\n\n✓ Interrompido pelo usuário")
    finally:
        server.stop()


if __name__ == "__main__":
    asyncio.run(main())
