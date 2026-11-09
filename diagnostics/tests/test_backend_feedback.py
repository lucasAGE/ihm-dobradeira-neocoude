import asyncio
import json
import unittest
from diagnostics.tests.runtime_fixture import MAP, manager_fixture, feedback_frames


class BackendFeedbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager, self.client, self.logger = manager_fixture()

    async def test_startup_is_unknown_and_json_serializable(self):
        state = json.loads(json.dumps(self.manager.get_state(), allow_nan=False))
        self.assertIsNone(state['encoder_raw'])
        self.assertIsNone(state['speed_class'])
        self.assertIsNone(state['pedal_segura'])
        self.assertIsNone(state['encoder_direction'])
        self.assertEqual(state['machine_state_name'], 'DESCONHECIDO')
        self.assertIsNone(state['machine_state_address'])
        self.assertEqual(set(state['inputs']), set(MAP.DIGITAL_INPUTS))
        self.assertEqual(set(state['outputs']), set(MAP.DIGITAL_OUTPUTS))
        self.assertTrue(all(value is None for value in state['inputs'].values()))
        self.assertEqual(self.client.calls, [])

    async def test_false_failure_exception_and_recovery_are_distinct_for_every_bit_group(self):
        for group, mapping, method in [('inputs', MAP.DIGITAL_INPUTS, self.manager.read_inputs),
                                       ('outputs', MAP.DIGITAL_OUTPUTS, self.manager.read_outputs),
                                       ('control_bits', MAP.CONTROL_BITS, self.manager.read_control_bits)]:
            names = list(mapping)
            self.assertTrue(await method())  # all legitimate false bits
            key = f'{group}.{names[0]}'
            previous_success = self.manager.machine_state['read_quality'][key]['last_success_at']
            self.client.coils[mapping[names[0]]] = None
            self.client.coils[mapping[names[1]]] = OSError('simulated')
            self.assertFalse(await method())
            state = self.manager.get_state()
            self.assertIsNone(state[group][names[0]])
            self.assertIsNone(state[group][names[1]])
            self.assertIs(state[group][names[-1]], False)
            self.assertEqual(state['read_quality'][key]['success_count'], 1)
            self.assertEqual(state['read_quality'][key]['error_count'], 1)
            self.assertEqual(state['read_quality'][key]['last_success_at'], previous_success)
            self.assertEqual(state['read_quality'][f'{group}.{names[1]}']['last_error'], 'exception:OSError')
            self.client.coils[mapping[names[0]]] = False
            self.client.coils[mapping[names[1]]] = True
            self.assertTrue(await method())
            quality = self.manager.machine_state['read_quality'][key]
            self.assertEqual(quality['status'], 'ok')
            self.assertEqual(quality['success_count'], 2)
            self.assertEqual(quality['error_count'], 1)
            self.assertIsNone(quality['last_error'])

    async def test_partial_state_failure_never_reports_idle_even_if_idle_read_succeeds(self):
        self.assertTrue(await self.manager.read_machine_states())
        self.assertEqual(self.manager.get_state()['machine_state_name'], 'PARADA')
        self.client.coils[MAP.MACHINE_STATES['ST_EMERGENCIA']] = None
        self.assertFalse(await self.manager.read_machine_states())
        state = self.manager.get_state()
        self.assertEqual(state['machine_state_name'], 'DESCONHECIDO')
        self.assertEqual(state['machine_state_error'], 'read_failed')
        self.assertIsNone(state['machine_state_address'])
        self.assertIsNone(state['states']['ST_EMERGENCIA'])
        self.assertIs(state['states']['ST_IDLE'], True)

    async def test_all_failed_no_active_or_conflicting_states_are_unknown_then_recover(self):
        for value, reason in [(None, 'read_failed'), (False, 'no_active_state'), (True, 'multiple_active_states')]:
            self.client.coils.update(dict.fromkeys(MAP.MACHINE_STATES.values(), value))
            self.assertFalse(await self.manager.read_machine_states())
            self.assertEqual(self.manager.get_state()['machine_state_error'], reason)
            self.assertIsNone(self.manager.get_state()['machine_state_address'])
        self.client.coils.update(dict.fromkeys(MAP.MACHINE_STATES.values(), False))
        self.client.coils[MAP.MACHINE_STATES['ST_IDLE']] = True
        self.assertTrue(await self.manager.read_machine_states())
        self.assertEqual(self.manager.get_state()['machine_state_name'], 'PARADA')

    async def test_encoder_failure_clears_values_without_inventing_movement_and_zero_recovers(self):
        self.client.registers[MAP.ENCODER['ANGLE_MSW']] = 399
        self.assertTrue(await self.manager.read_encoder())
        self.client.registers[MAP.ENCODER['ANGLE_MSW']] = None
        self.assertFalse(await self.manager.read_encoder())
        state = self.manager.get_state()
        for key in ('encoder_raw', 'encoder_degrees', 'encoder_pulses', 'encoder_degrees_disco', 'encoder_moving', 'encoder_angle'):
            self.assertIsNone(state[key])
        self.client.registers[MAP.ENCODER['ANGLE_MSW']] = 0
        self.assertTrue(await self.manager.read_encoder())
        self.assertEqual(self.manager.get_state()['encoder_raw'], 0)
        self.assertIsNone(self.manager.get_state()['encoder_moving'])
        self.assertTrue(await self.manager.read_encoder())
        self.assertIs(self.manager.get_state()['encoder_moving'], False)

    async def test_invalid_driver_values_are_errors_not_boolean_coercions(self):
        for bad in ('false', 0, 1, [], {}):
            self.client.coils[MAP.DIGITAL_INPUTS['E6']] = bad
            self.assertFalse(await self.manager.read_inputs())
            self.assertIsNone(self.manager.machine_state['inputs']['E6'])
        for bad in (True, -1, 65536, float('nan'), '42'):
            self.client.registers[MAP.ENCODER['ANGLE_MSW']] = bad
            self.assertFalse(await self.manager.read_encoder())
            self.assertIsNone(self.manager.machine_state['encoder_raw'])

    async def test_registers_angles_aliases_and_leds_clear_after_failure(self):
        await self.manager.read_work_registers()
        await self.manager.read_angles()
        await self.manager.read_outputs()
        self.assertEqual(self.manager.get_state()['target_angle'], 90.0)
        self.client.registers.update(dict.fromkeys(self.client.registers))
        self.client.coils[MAP.DIGITAL_OUTPUTS['S4']] = None
        self.assertFalse(await self.manager.read_work_registers())
        self.assertFalse(await self.manager.read_angles())
        self.assertFalse(await self.manager.read_outputs())
        state = self.manager.get_state()
        for key in ('target_angle', 'dobra_atual', 'contador_pecas', 'velocidade_rpm', 'speed_class', 'bend_1_left'):
            self.assertIsNone(state[key])
        self.assertIsNone(state['leds']['LED1'])

    async def test_aliases_preserve_pedal_true_and_unknown_direction(self):
        self.client.coils[MAP.CONTROL_BITS['PEDAL_SEGURA']] = True
        await self.manager.read_control_bits()
        self.assertIs(self.manager.get_state()['pedal_segura'], True)
        self.client.coils[MAP.CONTROL_BITS['DIR_AVANCO']] = None
        await self.manager.read_control_bits()
        self.assertIsNone(self.manager.get_state()['encoder_direction'])

    async def test_poll_result_counts_failure_and_preserves_existing_read_cadence(self):
        self.client.registers[MAP.ENCODER['ANGLE_MSW']] = None
        self.assertFalse(await self.manager.poll_once())
        first = self.manager.get_state()
        self.assertFalse(first['poll_ok'])
        self.assertEqual(first['poll_count'], 1)
        self.assertNotIn(('coil', MAP.DIGITAL_INPUTS['E0']), self.client.calls)
        self.assertNotIn(('register', MAP.BEND_ANGLES['ANGULO_1_READ']), self.client.calls)
        self.manager.force_angle_read = True
        self.client.registers[MAP.ENCODER['ANGLE_MSW']] = 0
        self.assertTrue(await self.manager.poll_once())
        self.assertIn(('coil', MAP.DIGITAL_INPUTS['E7']), self.client.calls)
        self.assertIn(('coil', MAP.DIGITAL_OUTPUTS['S7']), self.client.calls)
        self.assertEqual(self.manager.get_state()['read_quality']['encoder_raw']['success_count'], 1)

    async def test_failed_scan_cannot_complete_a_bend_or_bridge_a_gap(self):
        self.manager.machine_state['poll_count'] = 1
        self.manager.force_angle_read = True
        await self.manager.poll_once()  # observed idle baseline
        self.client.coils[MAP.MACHINE_STATES['ST_IDLE']] = False
        self.client.coils[MAP.MACHINE_STATES['ST_DOBRANDO']] = True
        await self.manager.poll_once()
        self.assertIsNotNone(self.manager._bend_start_time)
        self.client.coils[MAP.MACHINE_STATES['ST_IDLE']] = None
        await self.manager.poll_once()
        self.client.coils[MAP.MACHINE_STATES['ST_IDLE']] = True
        self.client.coils[MAP.MACHINE_STATES['ST_DOBRANDO']] = False
        await self.manager.poll_once()
        self.logger.log_bend.assert_not_called()
        self.assertIsNone(self.manager._bend_start_time)

    async def test_healthy_bend_transition_still_logs(self):
        self.manager.machine_state['poll_count'] = 1
        self.manager.force_angle_read = True
        await self.manager.poll_once()
        self.client.coils[MAP.MACHINE_STATES['ST_IDLE']] = False
        self.client.coils[MAP.MACHINE_STATES['ST_DOBRANDO']] = True
        await self.manager.poll_once()
        self.client.coils[MAP.MACHINE_STATES['ST_IDLE']] = True
        self.client.coils[MAP.MACHINE_STATES['ST_DOBRANDO']] = False
        await self.manager.poll_once()
        self.logger.log_bend.assert_called_once()

    async def test_transport_snapshots_cover_success_failure_recovery_under_frame_limit(self):
        frames = await feedback_frames()
        self.assertEqual([f['data']['inputs']['E6'] for f in frames], [None, False, None, False])
        self.assertEqual([f['data']['machine_state_name'] for f in frames], ['DESCONHECIDO', 'PARADA', 'DESCONHECIDO', 'PARADA'])
        for frame in frames:
            self.assertLess(len(json.dumps(frame, allow_nan=False).encode('utf-8')), 65536)
