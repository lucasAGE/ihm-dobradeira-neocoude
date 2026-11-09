# NEOCOUDE-HD-15 Web HMI

> **Manutenção e auditoria da plataforma (09/11/2026):** comece pelo
> [kit de diagnóstico somente leitura](diagnostics/README.md) e pelo
> [relatório de auditoria](docs/diagnostico/AUDITORIA.md).
> Para a manutenção pela rede, siga o [passo a passo de atualização e teste](docs/diagnostico/ATUALIZACAO_EM_CAMPO.md).
> Os estados históricos de validação neste repositório não certificam a instalação atual.
> Não execute os testes antigos contra a máquina: alguns escrevem saídas e registradores.

Modern web-based Human-Machine Interface for the Trillor NEOCOUDE-HD-15 rebar bending machine controlled by Atos MPC4004 PLC.

## Project Overview

This system replaces the damaged physical HMI (model 4004.95C) with a responsive web interface accessible from any tablet or device with a browser.

### Architecture

```
┌─────────────┐      RS485       ┌──────────────┐      WiFi        ┌─────────────┐
│   PLC       │ ←────────────→ │  Ubuntu      │ ←────────────→ │  Tablet     │
│  (Slave)    │   Modbus RTU   │  Server      │   WebSocket    │  (Browser)  │
│  MPC4004    │                │  (Master)    │                │             │
└─────────────┘                └──────────────┘                └─────────────┘
```

### Technology Stack

- **Backend**: Python 3 with `asyncio`, `websockets`, and `pymodbus`
- **Frontend**: Pure HTML5/CSS3/JavaScript (vanilla, no frameworks)
- **Protocol**: Modbus RTU over RS485, WebSocket for browser communication
- **Development**: Web-first prototyping (ready for ESP32/MicroPython migration)

## Quick Start

### 1. Install Dependencies

```bash
pip3 install -r requirements.txt
```

Required packages:
- `websockets` - WebSocket server
- `pymodbus` - Modbus RTU communication

### 2. Run in Stub Mode (No PLC Required)

For development and testing without PLC hardware:

```bash
python3 main_server.py
```

The server will start on `ws://localhost:8080` in stub mode.

### 3. Open Web Interface

Open `index.html` in any modern browser:

```bash
firefox index.html
# or
google-chrome index.html
# or simply double-click index.html
```

The interface will automatically connect to the WebSocket server.

### 4. Run in Live Mode (With PLC)

To connect to real PLC hardware:

```bash
python3 main_server.py --live --port /dev/ttyUSB0
```

Options:
- `--live`: Enable live mode (connect to real PLC)
- `--port`: Serial port for RS485 converter (default: `/dev/ttyUSB0`)

## Features

### Frontend Tabs

1. **Operação** (Operation)
   - Real-time encoder angle display
   - Virtual keyboard (K0-K9, S1/S2, arrows, ESC, EDIT, ENTER)
   - Setpoint inputs for bend angles

2. **Diagnóstico** (Diagnostics)
   - Digital twin with E0-E7 inputs as virtual LEDs
   - S0-S7 outputs as virtual LEDs
   - Real-time I/O monitoring

3. **Logs e Produção** (Logs & Production)
   - Runtime counter (active when cycle running)
   - Alert log with timestamps
   - Production tracking

4. **Configuração** (Configuration)
   - WiFi settings (will be enabled in ESP32 version)
   - System configuration

### Error Handling

- **Red "DESLIGADO" overlay**: WebSocket connection lost
- **Orange "FALHA CLP" overlay**: Modbus communication error
- **Auto-reconnect**: Attempts reconnection every 3 seconds
- **Graceful degradation**: System never crashes on communication failures

## File Structure

```
.
├── modbus_map.py          # Central Modbus address configuration
├── modbus_client.py       # Modbus RTU client (stub + live mode)
├── state_manager.py       # AsyncIO state polling (250ms cycle)
├── main_server.py         # WebSocket server
├── index.html             # Frontend web interface
├── requirements.txt       # Python dependencies
├── CLAUDE.md             # Technical documentation for Claude Code
└── README.md             # This file
```

## Modbus Configuration

### Serial Port Settings
- **Baudrate**: 57600
- **Parity**: None
- **Stop bits**: 1
- **Data bits**: 8
- **PLC Slave Address**: Read from register 0x1988 (6536 decimal)

### Critical Requirements
- State `0BE` (190 decimal) must be ON in PLC ladder logic to enable Modbus
- RS485 wiring: Ensure A/B pairs are not inverted
- USB-RS485 converter appears as `/dev/ttyUSB0` or `/dev/ttyUSB1`

## Development Workflow

1. **Develop in stub mode** - Test web interface without PLC
2. **Test functionality** - Verify all buttons and displays work
3. **Connect to PLC** - Switch to live mode with `--live` flag
4. **Map ladder registers** - Analyze `clp.sup` to fill placeholder addresses
5. **ESP32 migration** - Port to MicroPython (minimal changes needed)

## Button Mapping

Virtual keyboard buttons map to Modbus coils via Function 0x05 (Force Single Coil):

| Button | Address (Hex) | Address (Dec) |
|--------|---------------|---------------|
| K1-K9  | 0x00A0-0x00A8 | 160-168      |
| K0     | 0x00A9        | 169          |
| S1     | 0x00DC        | 220          |
| S2     | 0x00DD        | 221          |
| ▲      | 0x00AC        | 172          |
| ▼      | 0x00AD        | 173          |
| ESC    | 0x00BC        | 188          |
| EDIT   | 0x0026        | 38           |
| ENTER  | 0x0025        | 37           |

Each button press simulates:
1. Write coil to TRUE
2. Wait 100ms
3. Write coil to FALSE

## Encoder Reading

The encoder angle is read as a **32-bit value** from two consecutive registers:

- **MSW** (Most Significant Word): 0x04D6 (1238 decimal)
- **LSW** (Least Significant Word): 0x04D7 (1239 decimal)

Final value = `(MSW << 16) | LSW`

## Testing

### Test Individual Modules

```bash
# Test Modbus address map
python3 modbus_map.py

# Test Modbus client (stub mode)
python3 modbus_client.py

# Test state manager (async polling)
python3 state_manager.py
```

### Test Complete System

1. Start server:
   ```bash
   python3 main_server.py
   ```

2. Open `index.html` in browser

3. Click virtual buttons and observe:
   - Server logs show button presses
   - Encoder angle updates (simulated in stub mode)
   - Digital I/O LEDs respond to state changes

## Future Features

Placeholder functions are included for:

- **Telegram Alerts**: `send_telegram_alert()` in `main_server.py`
- **Google Sheets Logging**: `log_to_sheets()` in `main_server.py`

These will be implemented when needed.

## Troubleshooting

### Cannot connect to PLC

1. Verify RS485 wiring (A/B pairs not inverted)
2. Check baudrate setting (should be 57600)
3. Ensure state `0BE` (190 dec) is ON in ladder logic
4. Check serial port: `ls /dev/ttyUSB*`

### WebSocket won't connect

1. Ensure server is running: `python3 main_server.py`
2. Check console for errors
3. Verify port 8080 is not in use: `netstat -an | grep 8080`

### 32-bit values incorrect

- Remember: Even address = MSW, Odd address = LSW
- Byte order: Big-endian within each 16-bit word
- Use `combine_32bit_registers()` helper function

## Migration to ESP32

The code is structured for easy porting to ESP32/MicroPython:

1. Replace `websockets` with `uasyncio` + MicroPython WebSocket
2. Replace `pymodbus` with custom Modbus RTU implementation
3. Add WiFi AP mode for tablet connection
4. Add ESP32 sensor readings (temperature, etc.)

Minimal changes required - architecture is designed for portability.

## License

Internal project for W&CO / Camargo Steel.

## Support

For issues or questions, contact the development team.

---

**Status**: ✅ Core implementation complete, ready for PLC integration testing
