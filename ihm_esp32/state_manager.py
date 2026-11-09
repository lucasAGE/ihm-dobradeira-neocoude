#!/usr/bin/env python3
"""
State Manager - IHM Web Dobradeira (Novo Ladder)
================================================

Gerenciador de estado da maquina baseado no novo programa ladder
com maquina de 8 estados distintos.

Referencia: PROJETO_LADDER_NOVO.md
"""

import asyncio
import copy
import time
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from uuid import uuid4
from modbus_client import ModbusClientWrapper
import modbus_map as mm
from bend_logger import get_bend_logger


class MachineStateManager:
    """
    Gerenciador de estado da maquina com suporte a maquina de estados.
    """

    def __init__(self, modbus_client: ModbusClientWrapper, poll_interval: float = 0.25):
        """
        Inicializa gerenciador de estado.

        Args:
            modbus_client: Cliente Modbus (stub ou real)
            poll_interval: Intervalo de polling em segundos (padrao 250ms)
        """
        self.client = modbus_client
        self.poll_interval = poll_interval
        self.running = False

        # MELHORADO 08/Fev/2026: Flag para forçar leitura imediata de ângulos
        # Usado após escrita de ângulo para confirmação rápida
        self.force_angle_read = False

        # NOVO 08/Fev/2026: Sistema de auditoria de dobras
        # Detecta quando uma dobra é completada e registra automaticamente
        self._previous_state = None
        self._bend_start_time = None
        self._bend_start_angle = None
        self._bend_target_angle = None
        self._bend_logger = get_bend_logger(tolerance=2.0)

        # Callback para notificar quando uma dobra é registrada
        self.on_bend_logged = None  # Será setado pelo main_server

        # REMOVIDO: Filtro digital (CLP já fornece valor preciso 0-399)

        # Estado completo da maquina
        self.machine_state: Dict[str, Any] = {
            # Encoder / Posicao
            'encoder_raw': 0,
            'encoder_degrees': 0.0,

            # Angulos programados (0 até leitura do CLP)
            'angles': {
                'bend_1': 0.0,
                'bend_2': 0.0,
                'bend_3': 0.0,
            },

            # Angulo alvo atual
            'target_angle': 0.0,

            # Estado da maquina (novo ladder)
            'machine_state_address': 0x0300,  # Endereco do estado ativo
            'machine_state_name': 'PARADA',
            'machine_state_description': 'Maquina parada. Pressione o pedal para iniciar.',
            'machine_state_color': 'gray',
            'machine_state_icon': '⏸️',

            # Estados individuais (M000-M008)
            'states': {
                'ST_IDLE': False,
                'ST_AGUARDA_DIRECAO': False,
                'ST_DOBRANDO': False,
                'ST_RETORNANDO': False,
                'ST_AGUARDA_PROXIMA': False,
                'ST_COMPLETO': False,
                'ST_EMERGENCIA': False,
                'ST_MANUAL': False,
                'ST_CALIBRACAO': False,
            },

            # Bits de controle (B000-B007)
            'control_bits': {
                'DIR_AVANCO': False,
                'DIR_RECUO': False,
                'MODO_AUTO': False,
                'MODO_MANUAL': False,
                'PEDAL_SEGURA': False,
                'NA_POSICAO_ZERO': False,
                'ATINGIU_ANGULO': False,
                'HABILITADO': False,
            },

            # Entradas digitais (E0-E7)
            'inputs': {
                'E0': False,  # Sensor Zero
                'E2': False,  # Pedal Avanco
                'E3': False,  # Pedal Parada
                'E4': False,  # Pedal Recuo
                'E5': False,  # Sensor Seguranca
                'E6': False,  # Botao Emergencia
            },

            # Saidas digitais (S0-S7)
            'outputs': {
                'S0': False,  # Motor Avanco
                'S1': False,  # Motor Recuo
                'S2': False,  # Inversor
                'S4': False,  # LED Dobra 1
                'S5': False,  # LED Dobra 2
                'S6': False,  # LED Dobra 3
            },

            # Registros de trabalho
            'dobra_atual': 1,
            'contador_pecas': 0,
            'velocidade_rpm': 5.0,

            # LEDs (para compatibilidade)
            'leds': {
                'LED1': False,
                'LED2': False,
                'LED3': False,
                'LED4': False,
                'LED5': False,
            },

            # Calibracao (Estado 8) - DESATIVADO 02/Jan/2026
            # 'calibration': {
            #     'active': False,
            #     'step_code': 0,
            #     'step_name': 'Inativo',
            #     'step_description': '',
            #     'progress': 0,
            #     'resultado_zero': 0,
            #     'resultado_inercia': 0,
            #     'resultado_offset': 0,
            # },

            # Metadados
            'connected': False,
            'modbus_connected': False,
            'last_update': None,
            'poll_count': 0,
        }

        # A value is unknown until its own read succeeds, including at startup.
        for key in ('encoder_raw', 'encoder_degrees', 'encoder_degrees_disco',
                    'encoder_pulses', 'encoder_moving', 'target_angle',
                    'dobra_atual', 'contador_pecas', 'velocidade_rpm'):
            self.machine_state[key] = None
        for group, mapping in (('states', mm.MACHINE_STATES),
                               ('control_bits', mm.CONTROL_BITS),
                               ('inputs', mm.DIGITAL_INPUTS),
                               ('outputs', mm.DIGITAL_OUTPUTS)):
            self.machine_state[group] = dict.fromkeys(mapping)
        self.machine_state['angles'] = dict.fromkeys(('bend_1', 'bend_2', 'bend_3'))
        self.machine_state['leds'] = dict.fromkeys(self.machine_state['leds'])
        self.machine_state['feedback_version'] = 1
        self.machine_state['feedback_session'] = uuid4().hex
        self.machine_state['poll_ok'] = None
        quality_keys = ['encoder_raw', 'dobra_atual', 'contador_pecas', 'velocidade_rpm']
        for group in ('inputs', 'outputs', 'states', 'control_bits', 'angles'):
            quality_keys.extend(f'{group}.{name}' for name in self.machine_state[group])
        self.machine_state['read_quality'] = {key: {
            'status': 'not_read', 'last_attempt_at': None, 'last_success_at': None,
            'success_count': 0, 'error_count': 0, 'last_error': None} for key in quality_keys}
        self._unknown_machine_state('not_read')

    def _unknown_machine_state(self, reason):
        self.machine_state.update(machine_state_address=None,
            machine_state_name='DESCONHECIDO', machine_state_color='gray',
            machine_state_icon='?', machine_state_error=reason,
            machine_state_description='Estado indisponível: leitura incompleta ou estados inconsistentes.')

    async def _read_observation(self, key, address, *, bit=False, quality_store=None):
        """One existing read, with quality recorded independently of its value.

        The Modbus wrapper reports None for multiple failure types; do not guess
        CRC/timeout from that sentinel. No retries, new master or writes here.
        """
        error = None
        value = None
        try:
            reader = self.client.read_coil if bit else self.client.read_register
            value = await asyncio.to_thread(reader, address)
            if value is None:
                error = 'read_failed'
            elif (type(value) is not bool if bit else
                  type(value) is not int or not 0 <= value <= 65535):
                error = 'invalid_value'
                value = None
        except Exception as exc:
            # Exception type is sufficient; do not publish driver/device details.
            error = 'exception:' + type(exc).__name__
        now = datetime.now(timezone.utc).isoformat()
        store = self.machine_state['read_quality'] if quality_store is None else quality_store
        quality = store.setdefault(key, {
            'status': 'not_read', 'last_attempt_at': None, 'last_success_at': None,
            'success_count': 0, 'error_count': 0, 'last_error': None})
        quality.update(status='error' if error else 'ok', last_attempt_at=now, last_error=error)
        if error:
            quality['error_count'] += 1
        else:
            quality['success_count'] += 1
            quality['last_success_at'] = now
        return value

    async def _read_bits(self, group, mapping):
        # Publish a complete group after the cycle, not a mixture of old/new bits.
        values = {}
        qualities = {key: copy.deepcopy(value) for key, value in self.machine_state['read_quality'].items()
                     if key.startswith(group + '.')}
        for name, address in mapping.items():
            values[name] = await self._read_observation(f'{group}.{name}', address, bit=True, quality_store=qualities)
        self.machine_state[group] = values
        self.machine_state['read_quality'].update(qualities)
        return all(value is not None for value in values.values())

    def _update_target_angle(self):
        bend = self.machine_state['dobra_atual']
        self.machine_state['target_angle'] = (
            self.machine_state['angles'].get(f'bend_{bend}') if bend in (1, 2, 3) else None)

    async def read_encoder(self) -> bool:
        """Read the existing 16-bit register; preserve the established conversion."""
        pulses = await self._read_observation('encoder_raw', mm.ENCODER['ANGLE_MSW'])
        self.machine_state['encoder_raw'] = pulses
        if pulses is None:
            for key in ('encoder_pulses', 'encoder_degrees', 'encoder_degrees_disco', 'encoder_moving'):
                self.machine_state[key] = None
            self._last_encoder_pulsos = None
            return False
        normalized = pulses % 400
        self.machine_state['encoder_pulses'] = normalized
        self.machine_state['encoder_degrees_disco'] = normalized / 400.0 * 360.0
        self.machine_state['encoder_degrees'] = normalized / 400.0 * 180.0
        previous = getattr(self, '_last_encoder_pulsos', None)
        self.machine_state['encoder_moving'] = pulses != previous if previous is not None else None
        self._last_encoder_pulsos = pulses
        return True

    async def read_machine_states(self) -> bool:
        """Report an active state only after a complete, unambiguous scan."""
        complete = await self._read_bits('states', mm.MACHINE_STATES)
        active = [mm.MACHINE_STATES[name] for name, value in self.machine_state['states'].items()
                  if value is True]
        if not complete or len(active) != 1:
            reason = 'read_failed' if not complete else ('no_active_state' if not active else 'multiple_active_states')
            self._unknown_machine_state(reason)
            return False
        address = active[0]
        info = mm.get_state_info(address)
        self.machine_state.update(machine_state_address=address, machine_state_name=info['name'],
            machine_state_description=info['description'], machine_state_color=info['color'],
            machine_state_icon=info['icon'], machine_state_error=None)
        return True

    async def read_control_bits(self) -> bool:
        return await self._read_bits('control_bits', mm.CONTROL_BITS)

    async def read_inputs(self) -> bool:
        return await self._read_bits('inputs', mm.DIGITAL_INPUTS)

    async def read_outputs(self) -> bool:
        complete = await self._read_bits('outputs', mm.DIGITAL_OUTPUTS)
        for led, output in (('LED1', 'S4'), ('LED2', 'S5'), ('LED3', 'S6')):
            self.machine_state['leds'][led] = self.machine_state['outputs'].get(output)
        return complete

    async def read_work_registers(self) -> bool:
        complete = True
        for key, address in (('dobra_atual', mm.WORK_REGISTERS['DOBRA_ATUAL']),
                             ('contador_pecas', mm.WORK_REGISTERS['CONTADOR_PECAS']),
                             ('velocidade_rpm', mm.INVERTER['VELOCIDADE_INVERSOR'])):
            value = await self._read_observation(key, address)
            self.machine_state[key] = mm.register_to_rpm(value) if key == 'velocidade_rpm' and value is not None else value
            complete = complete and value is not None
        self._update_target_angle()
        return complete

    async def read_angles(self) -> bool:
        complete = True
        for bend in (1, 2, 3):
            value = await self._read_observation(f'angles.bend_{bend}', mm.BEND_ANGLES[f'ANGULO_{bend}_READ'])
            self.machine_state['angles'][f'bend_{bend}'] = mm.clp_to_real_angle(value) if value is not None else None
            complete = complete and value is not None
        self._update_target_angle()
        return complete

    def _detect_bend_completion(self):
        """
        Detecta quando uma dobra é completada e registra automaticamente.

        NOVO 08/Fev/2026: Sistema de auditoria de dobras.

        Detecta transição:
        - ST_DOBRANDO (0x0302) → qualquer outro estado = dobra completada
        - Registra ângulo programado vs ângulo executado
        - Emite alerta se erro exceder tolerância
        """
        current_state = self.machine_state.get('machine_state_address')
        required = ('encoder_degrees', 'dobra_atual', 'velocidade_rpm', 'target_angle')
        directions = self.machine_state.get('control_bits', {})
        if (current_state is None or any(self.machine_state.get(key) is None for key in required)
                or any(directions.get(key) is None for key in ('DIR_AVANCO', 'DIR_RECUO'))):
            # A lost observation is never a completed bend. Do not bridge the gap
            # with the last angle or fabricate a default angle/speed/direction.
            self._previous_state = None
            self._bend_start_time = self._bend_start_angle = self._bend_target_angle = None
            return

        # Detecta início de dobra (entrada em ST_DOBRANDO)
        if current_state == 0x0302 and self._previous_state is not None and self._previous_state != 0x0302:
            # Iniciou uma dobra
            self._bend_start_time = time.time()
            self._bend_start_angle = self.machine_state.get('encoder_degrees')
            dobra_atual = self.machine_state.get('dobra_atual', 1)
            self._bend_target_angle = self.machine_state['angles'].get(f'bend_{dobra_atual}', 90.0)
            print(f"🔄 Dobra {dobra_atual} INICIADA (alvo: {self._bend_target_angle}°)")

        # Detecta fim de dobra (saída de ST_DOBRANDO)
        elif self._previous_state == 0x0302 and current_state != 0x0302:
            # Dobra completada - registrar
            if self._bend_start_time is not None:
                duration_ms = int((time.time() - self._bend_start_time) * 1000)
                angle_executed = self.machine_state.get('encoder_degrees')
                angle_programmed = self._bend_target_angle
                dobra_atual = self.machine_state.get('dobra_atual', 1)
                speed_rpm = self.machine_state.get('velocidade_rpm', 5.0)

                # Determina direção
                dir_avanco = self.machine_state.get('control_bits', {}).get('DIR_AVANCO')
                direction = 'CCW' if dir_avanco else 'CW'

                # Registra a dobra
                result = self._bend_logger.log_bend(
                    bend_number=dobra_atual,
                    angle_programmed=angle_programmed,
                    angle_executed=angle_executed,
                    speed_rpm=speed_rpm,
                    direction=direction,
                    duration_ms=duration_ms
                )

                # Armazena resultado para broadcast
                self.machine_state['last_bend_result'] = result

                # Notifica via callback se configurado
                if self.on_bend_logged and callable(self.on_bend_logged):
                    try:
                        self.on_bend_logged(result)
                    except Exception as e:
                        print(f"⚠️ Erro no callback on_bend_logged: {e}")

                # Limpa estado temporário
                self._bend_start_time = None
                self._bend_start_angle = None
                self._bend_target_angle = None

        # Atualiza estado anterior
        self._previous_state = current_state

    async def poll_once(self) -> bool:
        """Keep the existing cadence; count attempts separately from valid reads."""
        self.machine_state['poll_count'] += 1
        results = []
        try:
            results.append(await self.read_encoder())
            results.append(await self.read_machine_states())
            results.append(await self.read_control_bits())
            if self.machine_state['poll_count'] % 2 == 0:
                results.append(await self.read_inputs())
                results.append(await self.read_outputs())
                results.append(await self.read_work_registers())
            if self.force_angle_read or self.machine_state['poll_count'] % 5 == 0:
                results.append(await self.read_angles())
                self.force_angle_read = False
            self._detect_bend_completion()
            self.machine_state['connected'] = bool(self.client.connected)
            self.machine_state['modbus_connected'] = bool(self.client.connected)
            self.machine_state['poll_ok'] = all(results)
            self.machine_state['last_update'] = datetime.now(timezone.utc).isoformat()
            return self.machine_state['poll_ok']
        except Exception as exc:
            print(f"Erro em poll_once: {type(exc).__name__}")
            self.machine_state['poll_ok'] = False
            self.machine_state['modbus_connected'] = False
            self._unknown_machine_state('poll_error')
            self._previous_state = None
            self._bend_start_time = self._bend_start_angle = self._bend_target_angle = None
            return False

    async def start_polling(self):
        """
        Inicia loop de polling com taxa OTIMIZADA para Modbus RTU.

        OTIMIZADO 02/Jan/2026: Máximo desempenho respeitando limites do Modbus
        - MOVIMENTO: 50ms (20 Hz) - máximo sustentável em Modbus RTU 57600bps
        - PARADO: 150ms (6.7 Hz) - economia de CPU
        - SEM FILTRO: CLP já fornece dados precisos
        - Leitura direta com timeout otimizado
        """
        self.running = True
        idle_interval = 0.3     # OTIMIZADO 06/Jan/2026: 300ms quando parado (3.3 Hz)
        fast_interval = 0.1     # OTIMIZADO 06/Jan/2026: 100ms durante movimento (10 Hz)

        print(f"🚀 State Manager OTIMIZADO para Modbus RTU iniciado!")
        print(f"   📊 Parado: {idle_interval*1000:.0f}ms ({1/idle_interval:.1f} Hz)")
        print(f"   ⚡ Movimento: {fast_interval*1000:.0f}ms ({1/fast_interval:.0f} Hz)")
        print(f"   🎯 Polling balanceado para estabilidade máxima")

        while self.running:
            start_time = time.time()
            await self.poll_once()
            elapsed = time.time() - start_time

            # Polling adaptativo: rápido durante movimento
            current_state = self.machine_state.get('machine_state_address', 0x0300)
            is_moving = current_state in [0x0302, 0x0303]  # ST_DOBRANDO ou ST_RETORNANDO

            # Também considera encoder_moving (detecta movimento fino)
            encoder_moving = self.machine_state.get('encoder_moving')

            # Usa intervalo rápido se em movimento
            target_interval = fast_interval if (is_moving or encoder_moving) else idle_interval

            sleep_time = max(0, target_interval - elapsed)
            await asyncio.sleep(sleep_time)
            await asyncio.sleep(0)  # Yield control

    def stop_polling(self):
        """Para loop de polling."""
        self.running = False
        print("✓ State Manager parado")

    def get_state(self) -> Dict[str, Any]:
        """
        Retorna estado completo com campos achatados para compatibilidade.

        CORRIGIDO 08/Fev/2026: Deep copy para evitar referências compartilhadas
        que impediam get_changes() de detectar mudanças em dicts aninhados.
        """
        state = copy.deepcopy(self.machine_state)

        # Achatar angulos para compatibilidade
        if 'angles' in state:
            state['bend_1_left'] = state['angles'].get('bend_1')
            state['bend_2_left'] = state['angles'].get('bend_2')
            state['bend_3_left'] = state['angles'].get('bend_3')

        # Alias para compatibilidade
        state['encoder_angle'] = state.get('encoder_degrees')
        speed = state.get('velocidade_rpm')
        state['speed_class'] = int(speed) if speed is not None else None

        # Feedback alias only: publish the actual read, including an unknown value.
        # This does not write or change the PLC pedal setting.
        state['pedal_segura'] = state['control_bits'].get('PEDAL_SEGURA')

        # Modo (para compatibilidade)
        state['mode_manual'] = state['states'].get('ST_MANUAL')

        # Encoder: Informações adicionais para visualização profissional
        state['encoder_pulses'] = state.get('encoder_pulses')  # Pulsos 0-399
        state['encoder_moving'] = state.get('encoder_moving')  # Flag movimento

        # Sentido de rotação (inferido dos bits de controle)
        dir_avanco = state.get('control_bits', {}).get('DIR_AVANCO')  # CCW
        dir_recuo = state.get('control_bits', {}).get('DIR_RECUO')    # CW

        if dir_avanco is None or dir_recuo is None or (dir_avanco and dir_recuo):
            state['encoder_direction'] = None
            state['encoder_direction_symbol'] = '?'
        elif dir_avanco:
            state['encoder_direction'] = 'CCW'  # Anti-horário
            state['encoder_direction_symbol'] = '⟲'
        elif dir_recuo:
            state['encoder_direction'] = 'CW'   # Horário
            state['encoder_direction_symbol'] = '⟳'
        else:
            state['encoder_direction'] = 'STOP'
            state['encoder_direction_symbol'] = '—'

        return state

    def get_changes(self, previous_state: Dict[str, Any]) -> Dict[str, Any]:
        """Retorna apenas mudancas."""
        changes = {}
        current = self.get_state()

        for key, value in current.items():
            if key not in previous_state or previous_state[key] != value:
                changes[key] = value

        return changes


if __name__ == "__main__":
    async def main():
        print("=== TESTE STATE MANAGER (NOVO LADDER) ===\n")
        client = ModbusClientWrapper(stub_mode=True)
        manager = MachineStateManager(client, poll_interval=1.0)

        print("Executando 5 ciclos de polling...\n")

        for i in range(5):
            await manager.poll_once()
            state = manager.get_state()
            print(f"Ciclo {i+1}:")
            print(f"  Encoder: {state['encoder_degrees']:.1f}°")
            print(f"  Estado: {state['machine_state_icon']} {state['machine_state_name']}")
            print(f"  Descricao: {state['machine_state_description']}")
            print(f"  Dobra atual: {state['dobra_atual']}")
            print(f"  Pecas: {state['contador_pecas']}")
            print(f"  Velocidade: {state['velocidade_rpm']:.1f} RPM")
            print(f"  PEDAL_SEGURA: {state['pedal_segura']}")
            print()
            await asyncio.sleep(0.5)

        print("✅ Teste concluido!")
        client.close()

    asyncio.run(main())
