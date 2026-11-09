"""Load only the state-manager class and pure map definitions, with fake I/O.

No production imports, Modbus library, serial port, service or log file is opened.
Also emits real get_state() snapshots for the JavaScript/browser regressions.
"""
import ast
import asyncio
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2] / 'ihm_esp32'


def definitions(path, allowed, symbols):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = [node for node in tree.body if isinstance(node, allowed)]
    future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[])), str(path), 'exec'), symbols)
    return symbols


MAP = SimpleNamespace(**definitions(ROOT / 'modbus_map.py', (ast.Assign, ast.FunctionDef), {}))


class FakeClient:
    connected = True

    def __init__(self):
        self.coils = {address: False for group in (MAP.MACHINE_STATES, MAP.CONTROL_BITS, MAP.DIGITAL_INPUTS, MAP.DIGITAL_OUTPUTS)
                      for address in group.values()}
        self.coils[MAP.MACHINE_STATES['ST_IDLE']] = True
        self.registers = {MAP.ENCODER['ANGLE_MSW']: 0, MAP.WORK_REGISTERS['DOBRA_ATUAL']: 1,
                          MAP.WORK_REGISTERS['CONTADOR_PECAS']: 0, MAP.INVERTER['VELOCIDADE_INVERSOR']: 0}
        self.registers.update({MAP.BEND_ANGLES[f'ANGULO_{bend}_READ']: 180 for bend in (1, 2, 3)})
        self.calls = []

    def _read(self, kind, address, source):
        self.calls.append((kind, address))
        value = source.get(address)
        if isinstance(value, Exception):
            raise value
        return value

    def read_coil(self, address):
        return self._read('coil', address, self.coils)

    def read_register(self, address):
        return self._read('register', address, self.registers)

    def __getattr__(self, name):
        raise AssertionError('Unexpected client operation: ' + name)


def manager_fixture():
    logger = Mock()
    symbols = {'asyncio': asyncio, 'copy': copy, 'datetime': datetime, 'timezone': timezone,
               'time': time, 'uuid4': uuid4, 'mm': MAP, 'get_bend_logger': lambda **_: logger,
               'print': Mock()}
    manager_type = definitions(ROOT / 'state_manager.py', (ast.ClassDef,), symbols)['MachineStateManager']
    client = FakeClient()
    return manager_type(client), client, logger


async def feedback_frames():
    manager, client, _ = manager_fixture()
    frames = [{'type': 'full_state', 'elapsed_ms': 0, 'data': manager.get_state()}]
    for index in range(1, 4):
        manager.machine_state['poll_count'] = index * 2 - 1
        manager.force_angle_read = True
        if index == 2:
            client.coils[MAP.DIGITAL_INPUTS['E6']] = None
            client.coils[MAP.MACHINE_STATES['ST_EMERGENCIA']] = None
            client.registers[MAP.ENCODER['ANGLE_MSW']] = None
        elif index == 3:
            client.coils[MAP.DIGITAL_INPUTS['E6']] = False
            client.coils[MAP.MACHINE_STATES['ST_EMERGENCIA']] = False
            client.registers[MAP.ENCODER['ANGLE_MSW']] = 0
        await manager.poll_once()
        frames.append({'type': 'state_update', 'elapsed_ms': index * 1000, 'data': manager.get_state()})
    return frames


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(asyncio.run(feedback_frames()), stream, indent=2, allow_nan=False)
