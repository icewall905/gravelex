package com.anopticlabs.gravel.pkjs

import coredevices.coreapp.TrackedTree
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Source sentinel for the PebbleKit JS WebSocket, which upstream moved out of the WebView into
 * `WebSocketManager` (Ktor). Its sockets never pass the WebView proxy override, and the dispatcher
 * that opens them is a JS interface the denied-session frame can call, so `WebViewJsRunner` must
 * hand the manager a gate that also requires this session's grant, and close its sockets whenever
 * a session ends. Checked as text with line comments removed.
 */
class NativeWebSocketGateSentinelTest {

    private val source by lazy {
        TrackedTree.file("libpebble3/src/androidMain/kotlin/io/rebble/libpebblecommon/js/WebViewJsRunner.kt").readText()
    }

    private val noGate = "the runner no longer gates its WebSocketManager on the session's grant"
    private val ungatedManager = "the runner's WebSocketManager no longer uses the session gate"
    private val openOnEnd = "endSession no longer closes the session's WebSockets"

    private fun problems(text: String): List<String> {
        val code = text.lines().joinToString("\n") { it.substringBefore("//") }
        return buildList {
            val gate = Regex(
                """(?m)^ {4}private val webSocketAccess = NetworkAccess \{ url, wait ->\n {8}if \(!networkAllowed \|\| denyConstruction\) \{\n {12}PluginNetworkVerdict\.Denied\([^\n]*\)\n {8}\} else \{\n {12}networkAccess\.check\(url, wait\)\n {8}\}\n {4}\}$""",
            )
            if (!gate.containsMatchIn(code)) add(noGate)
            val managers = Regex("""WebSocketManager\(([^\n]*)\)""").findAll(code).map { it.groupValues[1] }.toList()
            if (managers.size != 1 || !managers.single().trimEnd().endsWith(", webSocketAccess, dataUsage")) add(ungatedManager)
            val endSession = Regex("""private fun endSession\(view: WebView\) \{\n(.*?)\n    \}""", RegexOption.DOT_MATCHES_ALL)
                .find(code)?.groupValues?.get(1).orEmpty()
            if ("webSockets.close()" !in endSession) add(openOnEnd)
        }
    }

    @Test
    fun theRunnerGatesAndClosesItsWebSockets() {
        assertEquals(emptyList(), problems(source))
    }

    private fun String.edited(old: String, new: String): String {
        assertTrue(contains(old), "the runner no longer holds the text this edit replaces: $old")
        assertEquals(1, split(old).size - 1, "the text this edit replaces is not unique: $old")
        return replace(old, new)
    }

    @Test
    fun knownBadEditsAreNoticed() {
        val edits: Map<String, Pair<String, (String) -> String>> = mapOf(
            "the grant term is dropped" to
                (noGate to { it.edited("if (!networkAllowed || denyConstruction) {", "if (denyConstruction) {") }),
            "the construction term is dropped" to
                (noGate to { it.edited("if (!networkAllowed || denyConstruction) {", "if (!networkAllowed) {") }),
            "the manager gets the app gate alone" to
                (ungatedManager to { it.edited("httpClient, Uuid.parse(appInfo.uuid), webSocketAccess, dataUsage)", "httpClient, Uuid.parse(appInfo.uuid), networkAccess, dataUsage)") }),
            "endSession leaves sockets open" to
                (openOnEnd to { it.edited("        _readyState.value = false\n        webSockets.close()\n", "        _readyState.value = false\n") }),
        )
        for ((name, case) in edits) {
            val (expected, edit) = case
            assertEquals(listOf(expected), problems(edit(source)), name)
        }
    }
}
