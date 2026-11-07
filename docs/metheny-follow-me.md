# Pat Metheny "Follow Me" rig

A rig inspired by Pat Metheny's sound on "Follow Me", from *Imaginary Day* (1997).

**This is an informed approximation, and it hasn't been checked by ear yet.** No source was found for the patch on this recording, and a modeler's synth block isn't a Roland GR-300.

Spec: [`metheny-follow-me.json`](../rigs/metheny-follow-me.json)

## Footswitches

**Scenes (4-6):**

| Switch | Scene | Sound |
|---|---|---|
| 4 | `SYNTH` | Synth only: the lead voice |
| 5 | `BLEND` | Synth plus dry guitar |
| 6 | `CLEAN` | Guitar through the same split, no synth |

**Stomps (1-3):** Hybrid, Hybrid 2 and AIR Delay.

## Chain

Routing is Middle Split 3-4-3, with `Mix` panning path A hard left and path B hard right.

| Section | Block | Standing in for | Settings |
|---|---|---|---|
| Before split | Hybrid | GR-300 lead | Saw, Detune 1, 12 dB filter, Cutoff 55%, Filter depth 35%, no dry |
| Before split | Hybrid 2 | Blended version | As above, with Dry 70% and Synth 45% |
| Path A | Detune | Prime-Time delay | 14 ms, -3, Mix 50%, no feedback |
| Path A | Amp, `67 Black Duo` | Clean amp | Gain 20%, Bass 50%, Mid 45%, Treble 40%, Bright off |
| Path A | Cab, `2x12 Black Panel Duo` | | Dyn 57, on axis |
| Path B | Detune 2 | Prime-Time delay | 26 ms, +3, Mix 50%, no feedback |
| Path B | Amp 2, `67 Black Duo` | Clean amp | Same as path A |
| Path B | Cab 2, `2x12 Silver Cone` | | Dyn 57, on axis |
| After mix | AIR Delay | Ambience | 361 ms, Feedback 18%, Mix 10% |
| After mix | AIR Reverb | Ambience | Hall, Mix 18%, Size 50% |

## Evidence

| Choice | Basis |
|---|---|
| Guitar synth on this song | A [review of *Imaginary Day Live*](https://www.vintageguitar.com/3595/pat-metheny-imaginary-day-live/) has him switching to the GR-303 for it. The [album credits](https://en.wikipedia.org/wiki/Imaginary_Day) include guitar synth, without saying which tracks |
| 14 ms and 26 ms, left and right | Metheny's own description, [quoted on a forum](https://www.jazzguitar.be/forum/guitar-amps-gizmos/9319-poor-mans-pat-metheny-sound.html). It's a quote of his website, and may describe a different era |
| No feedback, about 50% mix | [A fan recipe](https://forum.fractalaudio.com/threads/getting-the-elusive-pat-metheny-es175-tone.91044/), not Metheny's settings |
| Small pitch offset | Players describe a slight sweep on the Prime-Time. The Detune block's fixed offset only approximates it, and the ±3 is a guess |
| Clean amps | His [GR-300 setups](https://killerguitarrigs.com/heres-what-pat-methenys-synth-guitar-is-really-like/) reportedly use clean amp models. The specific amp here is a stand-in |
| Synth settings, amp EQ, delay and reverb | **Guesses**, to tune by ear |

## Tuning

- Synth tracking depends on clean playing and your guitar, so try the neck pickup with your tone rolled back a little.
- Adjust Hybrid Cutoff and Filter depth first, as they shape the horn-like attack the most.
- Try different `Shape` and `Setup` values on Hybrid. `describe_block` lists them.
- If the two amps sound thin or quiet in mono, raise the `Mix` path levels. This may be phase interaction, though that's unconfirmed.
