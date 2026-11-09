"""Characterization of existing defects, NOT validation of the machine.

Compile only selected method AST nodes. Never import/start the application,
load pymodbus, connect to a tty, or execute old test_*.py scripts.
Broadcast assertions now protect corrected behavior. The staging-angle and
encoder-wrap assertions still document existing behavior, not machine approval.
"""
import ast
import asyncio
import copy
import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from diagnostics.tests.runtime_fixture import manager_fixture, MAP
import unittest

ROOT = Path(__file__).resolve().parents[2] / "ihm_esp32"


def method(filename, name, **symbols):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    selected = next(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, selected], type_ignores=[]))
    namespace = {"json": json, "copy": copy, **symbols}
    exec(compile(module, str(ROOT / filename), "exec"), namespace)
    return namespace[name]


class EndObservation(BaseException):
    pass


class RuntimeEvidenceTests(unittest.IsolatedAsyncioTestCase):



    async def test_encoder_wrap_keeps_raw_but_display_returns_to_zero(self):
        manager, client, _ = manager_fixture()
        client.registers[MAP.ENCODER["ANGLE_MSW"]] = 399
        self.assertTrue(await manager.read_encoder())
        self.assertAlmostEqual(manager.machine_state["encoder_degrees"], 179.55)
        client.registers[MAP.ENCODER["ANGLE_MSW"]] = 400
        self.assertTrue(await manager.read_encoder())
        self.assertEqual(manager.machine_state["encoder_raw"], 400)
        self.assertEqual(manager.machine_state["encoder_degrees"], 0)

    async def test_broadcast_preserves_a_change_during_send(self):
        state = {"encoder_raw": 1}
        messages, iterations = [], [0]
        manager = SimpleNamespace(get_state=lambda: copy.deepcopy(state),
                                  get_changes=lambda old: {k: v for k, v in state.items() if old.get(k) != v})

        async def sleep(_):
            iterations[0] += 1
            if iterations[0] == 4:
                raise EndObservation()

        class Client:
            async def send(self, message):
                messages.append(json.loads(message))
                state["encoder_raw"] = 2  # polling update while websocket send yields

        server = SimpleNamespace(clients={Client()}, state_manager=manager)
        broadcast = method("main_server.py", "broadcast_loop", asyncio=SimpleNamespace(sleep=sleep),
                           time=SimpleNamespace(time=lambda: 123), websockets=SimpleNamespace(exceptions=SimpleNamespace(ConnectionClosed=ConnectionError)))
        with self.assertRaises(EndObservation):
            await broadcast(server)
        self.assertEqual(state["encoder_raw"], 2)
        self.assertEqual([m["data"]["encoder_raw"] for m in messages], [1, 2])

    async def test_client_set_mutation_does_not_terminate_broadcast_task(self):
        iterations = [0]
        async def sleep(_):
            iterations[0] += 1
            if iterations[0] > 3:
                raise EndObservation()

        class Client:
            async def send(self, _):
                server.clients.add(object())  # another connection during await send

        server = SimpleNamespace(clients={Client()}, state_manager=SimpleNamespace(
            get_state=lambda: {"encoder_raw": 1}, get_changes=lambda old: {"encoder_raw": 1}))
        broadcast = method("main_server.py", "broadcast_loop", asyncio=SimpleNamespace(sleep=sleep),
                           time=SimpleNamespace(time=lambda: 123), websockets=SimpleNamespace(exceptions=SimpleNamespace(ConnectionClosed=ConnectionError)))
        with self.assertRaises(EndObservation):
            await broadcast(server)


    async def test_angle_confirmation_checks_staging_not_ladder_consumption(self):
        tree = ast.parse((ROOT / "modbus_map.py").read_text(encoding="utf-8"))
        mapping = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == "BEND_ANGLES" for t in n.targets))
        writes, reads, memory = [], [], {}

        def write(address, value):
            writes.append(address); memory[address] = value; return True

        def read(address):
            reads.append(address); return memory.get(address)

        client = SimpleNamespace(write_register=write, read_register=read)
        convert = method("modbus_map.py", "real_angle_to_clp")
        check = method("modbus_client.py", "write_bend_angle",
                       mm=SimpleNamespace(BEND_ANGLES=mapping, real_angle_to_clp=convert),
                       time=SimpleNamespace(sleep=lambda _: None), print=lambda *args: None)
        self.assertTrue(check(client, 1, 140, verify=True))
        self.assertEqual(writes, [0x0A00])
        self.assertEqual(reads, [0x0A00])
        self.assertEqual(memory[0x0A00], 280)
        self.assertNotIn(0x0942, reads)  # working setpoint in one archived Ladder variant


if __name__ == "__main__":
    unittest.main()
