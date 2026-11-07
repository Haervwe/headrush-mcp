# Mike Stern "Tipatina's" rigs

Rigs inspired by Mike Stern's sound on "Tipatina's", from *Play* (1999).

**These are informed approximations, tuned by ear on one rig and guitar.** No source was found for the gear on this recording or for his exact settings.

## Rigs

- [`stern-stereo-test.json`](../rigs/stern-stereo-test.json): **recommended.** Two parallel amps, as his rig is reported to use. By ear, the repo owner found it closer to the record than the single-amp version, even in mono.
- [`stern-tipatinas.json`](../rigs/stern-tipatinas.json): one amp, with stereo added after it. It also sounded good, and it uses about half the DSP.

## Footswitches

Both rigs share a layout.

**Scenes (4-6):**

| Switch | Scene | S1 Drive | B2 Drive | Short delay | Long delay | Reverb |
|---|---|---|---|---|---|---|
| 4 | `HEAD` | Off | Off | On | Off | On |
| 5 | `SOLO` | **On** | Off | On | Off | On |
| 6 | `BIG` | Off | **On** | On | **On** | On |

Detune stays on throughout. `SOLO` is the closest to how the song is played.

**Stomps (1-3):** S1 Drive, B2 Drive and the long delay.

## Settings

Block equivalents are inferred from their names, and aren't confirmed by HeadRush.

| Block | Standing in for | Settings |
|---|---|---|
| S1 Drive | Boss SD-1 | Drive 35%, Tone 55%, Level 60% |
| B2 Drive | Boss BD-2 | Gain 45%, Tone 50%, Level 50% |
| Amp, `67 Black Duo` | Fender Twin Reverb | Gain 32%, Bass 45%, Mid 50%, Treble 55%, Bright on |
| Cab, `2x12 Black Panel Duo` | Twin speakers | Dyn 57, on axis |
| Detune | Yamaha SPX-90 | -11 / +13, 9.1 / 4.1 ms, Mix 30% |
| AIR Delay | Boss DD-3, always on | 381 ms, Feedback 15%, Mix 8% |
| AIR Delay 2 | Second DD-3, for long delays | 801 ms, Feedback 25%, Mix 12% |
| Spring Reverb | Twin reverb | Mix 15% |

The first delay and mix settings were too wet by ear, so these were reduced. Stern's own numbers may differ.

### The two-amp version

- Routing: Middle Split 3-4-3, with `Mix` panning path A hard left and path B hard right.
- **Path A:** Detune (-11, 9.1 ms) → Amp → Cab with `2x12 Black Panel Duo`.
- **Path B:** Detune 2 (+13, 4.1 ms) → Amp 2 → Cab 2 with `2x12 Silver Cone`.
- Drives come before the split, and delays and reverb after the mix.

The aim is for each amp to carry its own pitch offset, so the effect happens between the speakers. It uses about 39% DSP, compared with about 20% for the single-amp rig.

**In mono**, it can sound quieter than expected and may need a few dB of boost. This might be phase interaction between the two amps, though that's unconfirmed. Adjust it to suit your setup with rig volume or `Mix` path levels.

## Evidence

| Choice | Basis |
|---|---|
| Regular delay always on, long delay occasional | [Stern's BOSS interview](https://www.boss.info/us/community/boss_users_group/815/) (first-hand, no numbers) |
| DS-1 on his records | Same interview. It sounded too nasal in this rig, so B2 Drive replaced it |
| SD-1 on a recent board | [Stompbox Book](https://stompboxbook.com/visiting-mike-stern-the-making-of-stompbox-book/), with a [board photo](https://stompboxbook.com/wp-content/uploads/2020/06/StompBox_5011.jpg) from 2020 |
| SPX-90 pitch shifting defines his sound | Stompbox Book |
| Two amps in stereo | [Shane Theriot](https://shanetheriot.com/videos/2040843) (second-hand) and [forum posts](https://forum.seymourduncan.com/threads/does-anyone-know-mike-sterns-rig-on-this.6201380/) |
| Pitch Change C program | [One forum post](https://forum.kemper-amps.com/forum/thread/23791-micro-pitch-with-adjustable-pitch-l-and-r-and-delay) (unsourced). Sources conflict on the patch number: 23, 54 and 55 are all reported |
| Detune values | **Not Stern's.** They're Michael Landau's published Pitch Change C values, from that same thread |
| Delay times, drive and amp settings | **Guesses**, as no source gives numbers |

The photo shows the board but not reliably readable knobs. Premier Guitar's 2018 Rig Rundown reportedly shows his long-delay settings on camera, but wasn't available to check.

## Tuning

- Your guitar matters: his Pacifica has a '59 in the neck and a Tele Hot Rail in the bridge, and a neck humbucker is the closest match.
- Set amp Gain and Level first, because they're the likeliest to be off for your guitar.
- Then set Detune Mix, as it defines the sound.
