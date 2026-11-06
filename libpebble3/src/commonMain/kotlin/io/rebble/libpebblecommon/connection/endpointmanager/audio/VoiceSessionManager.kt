package io.rebble.libpebblecommon.connection.endpointmanager.audio

import kotlinx.coroutines.CancellationException
import co.touchlab.kermit.Logger
import io.rebble.libpebblecommon.SystemAppIDs
import io.rebble.libpebblecommon.WatchConfigFlow
import io.rebble.libpebblecommon.connection.endpointmanager.CompanionAppLifecycleManager
import io.rebble.libpebblecommon.packets.AudioStream
import io.rebble.libpebblecommon.packets.AudioStreamSetupResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.IO
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.onStart
import com.anopticlabs.gravel.link.WatchLinkPace
import com.anopticlabs.gravel.watchapp.InjectedWatchAppCaptures
import io.rebble.libpebblecommon.di.ConnectionCoroutineScope
import io.rebble.libpebblecommon.packets.DictationResult
import io.rebble.libpebblecommon.packets.Result
import io.rebble.libpebblecommon.packets.Sentence
import io.rebble.libpebblecommon.packets.SessionSetupResult
import io.rebble.libpebblecommon.packets.SessionType
import io.rebble.libpebblecommon.packets.VoiceAttribute
import io.rebble.libpebblecommon.packets.VoiceAttributeType
import io.rebble.libpebblecommon.permissions.AppPermissions
import io.rebble.libpebblecommon.permissions.PermissionDecision
import io.rebble.libpebblecommon.plugin.PluginPermissions
import io.rebble.libpebblecommon.services.AudioStreamService
import io.rebble.libpebblecommon.services.VoiceService
import io.rebble.libpebblecommon.voice.TranscriptionProvider
import io.rebble.libpebblecommon.voice.TranscriptionResult
import io.rebble.libpebblecommon.voice.TranscriptionWord
import io.rebble.libpebblecommon.voice.toProtocol
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.transform
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.time.Duration.Companion.seconds
import kotlin.uuid.Uuid

/**
 * Protocol adapter for watch dictation: decodes the frame stream and
 * encodes the setup and dictation result packets, and hands the session
 * logic itself to [VoiceSessionCoordinator] (the deadline, the bound on a
 * recording the watch never ends, and the rule that a new setup supersedes
 * the session in flight).
 */
class VoiceSessionManager(
    private val voiceService: VoiceService,
    private val audioStreamService: AudioStreamService,
    private val watchScope: ConnectionCoroutineScope,
    private val transcriptionProvider: TranscriptionProvider,
    private val watchAppCaptures: InjectedWatchAppCaptures,
    private val linkPace: WatchLinkPace,
    private val companionAppLifecycleManager: CompanionAppLifecycleManager,
    private val audioFrameDecoder: AudioFrameDecoder,
    private val permissions: AppPermissions,
    private val watchConfig: WatchConfigFlow,
) {
    private val logger = Logger.withTag("VoiceSession")

    private suspend fun handleAudioStream(
        setupRequest: VoiceService.SessionSetupRequest,
        appInitiated: Boolean,
    ) {
        val encoderInfo = setupRequest.encoderInfo
        val sessionId = setupRequest.sessionId.toUShort()
        val subject = permissions.subjectOf(setupRequest.appUuid)
        if (!watchConfig.value.enablePlugins) { // Only enable for apps if plugins are enabled, otherwise we would default-allow
            logger.w { "Audio stream from ${setupRequest.appUuid} refused: permissions not enabled" }
            voiceService.send(makeAudioStreamSetupResult(Result.FailDisabled, sessionId, appInitiated))
            return
        }
        if (subject == null || permissions.request(subject, PluginPermissions.WATCH_MICROPHONE) != PermissionDecision.Granted) {
            logger.w { "Audio stream from ${setupRequest.appUuid} refused: microphone permission not granted" }
            voiceService.send(makeAudioStreamSetupResult(Result.FailDisabled, sessionId, appInitiated))
            return
        }
        val app = companionAppLifecycleManager.currentCompanionAppSessions.value
            .filterIsInstance<AudioStreamTarget>().firstOrNull { it.uuid == setupRequest.appUuid }
        if (app == null) {
            logger.w { "Audio stream from ${setupRequest.appUuid} refused: no companion accepts audio" }
            voiceService.send(makeAudioStreamSetupResult(Result.FailServiceUnavailable, sessionId, appInitiated))
            return
        }
        val decoder = encoderInfo?.let { audioFrameDecoder.open(it) }
        if (encoderInfo == null || decoder == null) {
            logger.w { "Audio stream with unsupported encoder: $encoderInfo" }
            voiceService.send(makeAudioStreamSetupResult(Result.FailServiceUnavailable, sessionId, appInitiated))
            return
        }
        var accepted = false
        var completed = false
        try {
            val pcm = flow {
                audioStreamService.dataFlowForSession(sessionId).collect { transfer ->
                    for (frame in transfer.frames) {
                        decoder.decode(frame.data.get())?.let { emit(it) }
                    }
                }
            }
            completed = streamAudioWhileGranted(permissions.grantedKeys(subject, listOf(PluginPermissions.WATCH_MICROPHONE))) {
                app.streamAudio(encoderInfo.sampleRate.toInt(), pcm) {
                    voiceService.send(makeAudioStreamSetupResult(Result.Success, sessionId, appInitiated))
                    accepted = true
                    logger.i { "Audio stream $sessionId from ${setupRequest.appUuid} started" }
                }
            }
            if (!completed && !accepted) {
                logger.w { "Audio stream from ${setupRequest.appUuid} refused: companion not ready" }
                voiceService.send(makeAudioStreamSetupResult(Result.FailServiceUnavailable, sessionId, appInitiated))
            } else if (completed) {
                logger.i { "Audio stream $sessionId ended" }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            logger.e(e) { "Audio stream $sessionId failed" }
            if (!accepted) {
                voiceService.send(makeAudioStreamSetupResult(Result.FailServiceUnavailable, sessionId, appInitiated))
            }
        } finally {
            decoder.close()
            if (accepted && !completed) {
                withContext(NonCancellable) {
                    withTimeoutOrNull(1.seconds) {
                        audioStreamService.send(AudioStream.StopTransfer(sessionId))
                    }
                }
            }
        }
    }

    private val _currentSession = MutableStateFlow<CurrentSession?>(null)
    val currentSession = _currentSession.asStateFlow()

    data class CurrentSession (
        val request: VoiceService.SessionSetupRequest,
        val result: CompletableDeferred<TranscriptionResult>
    )

    private fun makeSetupResult(
        sessionType: SessionType,
        result: Result,
        appInitiated: Boolean
    ): SessionSetupResult {
        val setupResult = SessionSetupResult(sessionType, result)
        if (appInitiated) {
            setupResult.flags.set(1u) // Indicates app-initiated session
        }
        return setupResult
    }

    private fun makeAudioStreamSetupResult(
        result: Result,
        sessionId: UShort,
        appInitiated: Boolean
    ): AudioStreamSetupResult {
        val setupResult = AudioStreamSetupResult(result, sessionId)
        if (appInitiated) {
            setupResult.flags.set(1u) // Indicates app-initiated session
        }
        return setupResult
    }

    private fun makeDictationResult(
        sessionId: UShort,
        result: Result,
        words: Iterable<TranscriptionWord>?,
        appUuid: Uuid
    ): DictationResult {
        return DictationResult(
            sessionId,
            result,
            buildList {
                words?.let {
                    add(VoiceAttribute(
                        id = VoiceAttributeType.Transcription.value,
                        content = VoiceAttribute.Transcription(
                            sentences = listOf(
                                Sentence(words.map { it.toProtocol() })
                            )
                        )
                    ))
                }
                if (appUuid != Uuid.NIL) {
                    add(VoiceAttribute(
                        id = VoiceAttributeType.AppUuid.value,
                        content = VoiceAttribute.AppUuid().apply {
                            uuid.set(appUuid)
                        }
                    ))
                }
            }
        ).apply {
            if (appUuid != Uuid.NIL) {
                flags.set(1u) // Indicates app-initiated session
            }
        }
    }

    private val coordinator = VoiceSessionCoordinator(
        scope = watchScope,
        setupRequests = voiceService.sessionSetupRequests,
        framesFor = { sessionId ->
            audioStreamService.dataFlowForSession(sessionId)
                .transform { transfer ->
                    transfer.frames
                        .map { frame -> frame.data.get() }
                        .forEach { emit(it) }
                }
        },
        sendSetupResult = { sessionType, result, appInitiated ->
            voiceService.send(makeSetupResult(sessionType, result, appInitiated))
        },
        sendDictationResult = { sessionId, result, appUuid ->
            voiceService.send(
                makeDictationResult(
                    sessionId = sessionId,
                    result = result.toProtocol(),
                    words = (result as? TranscriptionResult.Success)?.words,
                    appUuid = appUuid,
                )
            )
        },
        provider = transcriptionProvider,
        watchAppCaptures = watchAppCaptures.captures,
        linkPace = linkPace.pace,
        requestFastLink = linkPace::requestFast,
        streamAudio = { request -> handleAudioStream(request, request.appUuid != Uuid.NIL) },
        onSessionStarted = { request ->
            _currentSession.value = CurrentSession(request, CompletableDeferred())
        },
        onSessionEnded = { request, result ->
            _currentSession.value?.let { current ->
                if (current.request.sessionId == request.sessionId) {
                    current.result.complete(result)
                    _currentSession.value = null
                }
            }
        },
    )

    fun init() {
        watchScope.launch { coordinator.run() }
    }
}
