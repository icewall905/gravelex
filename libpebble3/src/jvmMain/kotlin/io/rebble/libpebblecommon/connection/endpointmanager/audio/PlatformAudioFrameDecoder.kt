package io.rebble.libpebblecommon.connection.endpointmanager.audio

import io.rebble.libpebblecommon.voice.VoiceEncoderInfo

internal actual fun platformAudioFrameDecoder(): AudioFrameDecoder = object : AudioFrameDecoder {
    override fun open(encoderInfo: VoiceEncoderInfo): AudioPcmDecoder? = null
}
