---
name: Bluetooth frame test
description: Use when writing or repairing a test for Bluetooth frame handling in the Beurer integration: outgoing command bytes, incoming GATT notifications, checksums, or hardware button events.
---

# Test a Bluetooth frame

Tests never touch hardware. `tests/conftest.py` mocks `bleak` and Home Assistant,
and the `beurer_instance` fixture gives you a controller that thinks it is
connected. The wire protocol itself is documented in `README.bluetooth.md`; read
it before you write a byte, because the existing tests are the second source of
truth and they disagree with your memory.

## Outgoing: what the lamp receives

`sendPacket` builds the frame and hands it to `_write`, so replace `_write` with a
recorder and assert on the payload. This is the idiom from
`tests/test_beurer_commands.py`:

```python
sent_packets: list[bytearray] = []


async def mock_write(data: bytearray) -> None:
    sent_packets.append(data)


beurer_instance._write = mock_write
beurer_instance._is_on = True

with patch("asyncio.sleep", AsyncMock()):
    await beurer_instance.enable_timer()

assert len(sent_packets) == 2  # ordering is part of the behaviour
assert sent_packets[0][7] == 0x38  # opcode: CMD_ENABLE_TIMER
assert sent_packets[1][7] == 0x33  # opcode: CMD_SET_TIMER_DURATION
```

The frame that `sendPacket` produces, so you can index it without guessing:

```text
0  1   2   3      4  5    6        7…        n    n+1 n+2 n+3
fe ef  0a  len+7  ab aa  len+2  <payload>  xor  55  0d  0a
```

Byte 7 is the first payload byte and therefore the opcode; byte 8 is the channel.
Assert the bytes that encode the behaviour (opcode, channel, value, number of
frames). A full-frame equality check is allowed when the whole frame is the
contract, but it turns every unrelated framing change into a failing test.

## Incoming: what the lamp reports

Call the handler directly with a real frame. This is the idiom from
`tests/test_beurer_notifications.py`:

```python
payload = bytearray([0xFE, 0xEF, 0x0C, 0x0B, 0xAB, 0xBB, 0x06, 0xE8, 0x00, 0x00, 0x00, 0xEE, 0x55, 0x0D, 0x0A])

char = MagicMock()
await beurer_instance.notification_handler(char, payload)

assert beurer_instance.is_on is False
```

Assert the state field *and* the consequence: a registered callback fired, a
packet was written back, a timer was cleared. Asserting only the field lets a
missing `trigger_entity_update()` through.

## Rules

- **Red first.** Write the test against the current code and watch it fail before
  you change the implementation. A test that never failed proves nothing.
- **A fresh instance per test.** The controller is stateful (connection, mode,
  last status query, event dedupe). Reusing one leaks state between tests; the
  fixture is function-scoped, so do not hoist it to module level.
- **Fixtures must be protocol-correct.** Copy real bytes from `README.bluetooth.md`
  or from a capture. Do not invent a frame and do not "adjust" a checksum to make
  a test pass: the incoming checksum is logged, not enforced, so a wrong checksum
  hides nothing but also proves nothing.
- **Hardware events arrive in bursts.** `0xE8`, `0xEB` and `0xEC` are
  retransmitted with non-identical bytes; `README.bluetooth.md` has the details.
  When you test deduplication, test both halves: the burst must collapse into one
  event, and a genuine second press after the window must still come through. An
  unbounded guard passes the first test and breaks the second.
- **Never weaken an assertion** to reach green. If a field is genuinely unknown,
  assert what is known and say what is not.

## Where to look

- `tests/test_beurer_commands.py` — outgoing commands, ordering, timer rules.
- `tests/test_beurer_notifications.py` — incoming frames, button events, reconnect.
- `tests/test_beurer_protocol.py` — framing and checksum helpers.
- `tests/test_beurer_command_lock.py` — concurrency between command sequences.
