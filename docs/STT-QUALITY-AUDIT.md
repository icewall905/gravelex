# Watch dictation quality investigation

Investigated 2026-10-24. Read-only inspection; no STT configuration changed.

## Current conclusion

The watch-specific server path has materially different recognition settings from the inspected HA Wyoming path. This is a concrete software suspect, not proof of the cause of a particular bad transcript. Watch capture is also a credible suspect, supported by historical upstream testing, but not yet measured on this user's current firmware. The installed phone's active STT URL/engine is unconfirmed: no ADB device was connected.

## Paths inspected

- Watch -> Speex frames -> GravelEx phone decoder -> 16 kHz mono PCM WAV -> configured HTTPS URL.
- `/qwen...` on the STT reverse proxy -> path rewrite -> TLS frontend -> Gravel shim -> Qwen3-ASR-1.7B.
- Bare STT hostname -> health-based failover chain. It is not equivalent to the `/qwen` route and may choose another model/backend.
- Inspected HA Wyoming service -> Qwen3-ASR-1.7B, without the watch shim. This does not establish which pipeline every satellite or phone microphone currently selects.

## Verified runtime differences

| Setting | Watch-specific shim | Inspected Wyoming service |
| --- | --- | --- |
| Model | Qwen3-ASR-1.7B | Qwen3-ASR-1.7B |
| Context prompt | 1,136 characters of smart-home vocabulary/context | Empty |
| Output token budget | 32 | 96 |
| Language | Forced English by shim | Default English; inspect individual client request for actual language |
| Filtering | Prompt-echo detection, unprompted retry, vocabulary guard | Separate gate configuration; denoise disabled and RMS gate effectively open |

The shim ignores incoming model/language/prompt values and uses its own settings. A retry following a detected prompt echo is discarded when it has at most two tokens, or (with vocabulary guard enabled) lacks a word from the configured vocabulary. The guard does not run on every first-pass result. A 32-token cap can truncate sufficiently long dictation; its impact on short commands remains unmeasured. These settings suit a restricted command endpoint more than unrestricted notes/replies.

Traefik's inspected configuration rewrites the path and selects an upstream; it does not transcode or preprocess audio. No evidence currently identifies Traefik as causing recognition degradation. Byte-for-byte request/audio comparison is still needed to rule out transport issues conclusively. A stale config comment calls one fallback Gemma, while the inspected backend is currently Qwen: runtime evidence takes precedence over comments.

## Phone and watch evidence

- `pebble/src/commonMain/kotlin/coredevices/pebble/services/HybridTranscription.kt`: accepted Speex sessions decode to 320 samples/frame, 16 kHz; failed decode returns an error rather than silently accepting damaged frames.
- `pebble/src/commonMain/kotlin/com/anopticlabs/gravel/watchapp/WatchSpeex.kt`: wideband decoder constants and frame handling.
- `util/src/commonMain/kotlin/coredevices/util/transcription/SelfHostedTranscriptionService.kt`: PCM buffered into WAV, with model/language fields; no gain correction, denoise or silence trimming in this upload path.
- `KNOWN_ISSUES.md`, “Watch dictation accuracy varies sharply between sessions”: historical upstream tests found some captures speech-poor despite adequate loudness, and first syllables sometimes missing when speaking immediately at the microphone icon. Those tests included older firmware and are not a diagnosis of this watch on 4.42.0. Mic occlusion, moisture/debris, firmware gain state and codec/transport remain candidates.
- Debug-only capture hooks retain the last 20 WAV/frame captures privately. Release builds do not expose that capture toggle; do not assume it can be enabled on the installed release.

## Controlled test plan

1. Confirm installed GravelEx engine, URL, model, language and watchapp. Record whether poor results occur in HA commands, notification replies or notes.
2. Capture paired known phrases: same room/distance, quiet then ordinary background noise; keep mic port clear, wait about one second after the recording icon. Include short commands and longer free text. Preserve intended text separately.
3. Retain encoded frames and decoded WAV privately. Measure duration, frame count, sample rate, RMS/peak/clipping, speech-band energy and start/end truncation. Listen to the decoded audio before changing recognition parameters.
4. Replay each identical WAV through existing watch shim, unprompted Qwen with matched language/token settings, and another available recognizer. Keep audio hashes and reference transcripts; score word error rate and empty/truncated results, plus latency.
5. Compare phone-mic audio through the same recognizer/settings. Clean phone audio succeeding while watch WAV fails across recognizers implicates capture/codec; identical watch audio improving with settings implicates server configuration.
6. Verify proxy versus direct upstream with the same payload and matched decoding parameters. Matching audio hashes/results reduces the likelihood of a proxy fault.
7. Change one setting at a time. Keep command-specific filtering separate from general dictation; do not indiscriminately enable denoise/AGC (historical satellite tests found aggressive denoise harmful).

No paired recordings or new accuracy measurements were collected in this inspection. Do not call the microphone defective or promise that a model/configuration change will fix it yet.

## Primary documentation

- [Pebble dictation lifecycle](https://developer.repebble.com/guides/events-and-services/dictation/)
- [Qwen3-ASR source and inference options](https://github.com/QwenLM/Qwen3-ASR)
