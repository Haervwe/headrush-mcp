# MIDI control

The Flex Prime can be controlled with MIDI messages, as an alternative to footswitches and to this server. **This server doesn't send MIDI.** You'd need a MIDI controller or interface, and this page lists what the pedal responds to.

From the [Flex Prime User Guide v5.2.0](https://cdn.inmusicbrands.com/Software/SGEE/52/HeadRush%20Flex%20Prime%20-%20User%20Guide%20-%20v5.2.0.pdf), pages 30, 63 and 66-67. Firmware 4.1.0 added much of this CC control; some, such as the Practice Tool CCs, came earlier.

## Connecting

- MIDI gear connects to the 1/8" (3.5 mm) MIDI input. The guide also says class-compliant USB-MIDI gear can connect to the USB-B port (p.66).
- Whether a computer connected over USB-B sees a MIDI port is unverified, so sending MIDI straight from a computer may need a separate MIDI interface.
- **Global Settings > MIDI** sets the channel (Omni or 1-16) and whether program changes are received (p.63).

## Program changes

Each rig has a **MIDI PROG** number from 1 to 128 in Hardware Assign. Program change 0 loads the rig set to 1, and so on up to 127 (p.30). Prog Change **Recv** must be on.

## Control changes

Most actions fire on any value from 0 to 127. The exceptions (p.67):

- **CC 1 and 2** (expression pedals) take the value as the pedal position.
- **CC 49-51** (footswitches) need 127 for the press, then 0 for the release. Sending only 127 fires that switch's hold function instead.
- **CC 64** (tap tempo) needs sending several times, like tapping.

### Footswitches, banks and scenes

| CC | Action |
|---|---|
| 14 | Internal expression pedal toe switch (A/B) |
| 16 | Previous rig |
| 17 | Next rig |
| 18 | Previous rig bank |
| 19 | Next rig bank |
| 20 | Footswitch bank A/B, switching between switches 1-3 and 4-6 |
| 21-26 | Scene 1-6 |
| 49-51 | Footswitch 1-3 |
| 75-88 | Toggle the block in slot 1-14 |
| 94 | Stomp footswitch mode |
| 95 | Hybrid footswitch mode |
| 96 | Setlist footswitch mode |
| 97 | Rig footswitch mode |

CC 18 and 19 move between banks of rigs, which are probably not the footswitch banks that CC 20 toggles. Whether CC 20 works without a hold set to Bank A/B (see the [README](../README.md#reaching-switches-4-6)) hasn't been tested.

### Expression and tempo

| CC | Action |
|---|---|
| 1 | Internal expression pedal |
| 2 | External expression pedal |
| 12 | Global tempo down |
| 13 | Global tempo up |
| 64 | Tap tempo |

### Screens

| CC | Action |
|---|---|
| 90 | Hands-Free, open or close |
| 91 | Looper, open or close |
| 92 | Tuner, open or close |
| 93 | Lock screen, open or close |

### Looper

| CC | Action |
|---|---|
| 65 | Half speed |
| 66 | Double speed |
| 67 | Half loop |
| 68 | Double loop |
| 69 | Start or stop |
| 70 | Record |
| 71 | Insert |
| 72 | Peel |
| 73 | Mute |
| 74 | Reverse |

### Drum machine

| CC | Action |
|---|---|
| 31 | Open or close |
| 32, 33 | Previous, next kit |
| 34, 35 | Previous, next style |
| 36, 37 | Previous, next variation |
| 38, 39 | Volume down, up |
| 40, 41 | Intensity down, up |
| 42 | Play or stop |
| 43 | Fill |
| 44 | Next or bridge |
| 45 | Outro |
| 46 | Mute |
| 47 | Accent |

### Practice tool

| CC | Action |
|---|---|
| 102 | Open or close |
| 103 | Play or pause |
| 104 | Stop |
| 105, 106 | Volume down, up |
| 107 | Loop in |
| 108 | Loop out |
| 109, 110 | Speed down, up |
| 111, 112 | Pitch down, up |
| 113, 114 | Previous, next |
| 115, 116 | Rewind, fast forward |
| 117 | Loop on or off |

## MIDI out

The pedal can also send up to five program change, control change or note messages when a rig loads, a scene fires or a footswitch is pressed (p.34-35). Those are set up on the pedal. This server can't set them yet. See the [API notes](api.md#scene-midi-out).
