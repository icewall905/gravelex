package com.anopticlabs.gravel.ui

import coredevices.pebble.ui.WatchHomeNavTab
import coredevices.pebble.ui.WatchHomeNavTab.*
import coredevices.util.CoreConfig
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class NotebookNavBarEntriesTest {
    private val config = CoreConfig(navBarTabs = listOf("WatchFaces", "Index", "Notebook", "Watches", "Health", "Notifications", "Settings"))

    @Test
    fun shownNotebookKeepsItsPlaceAndOverflowRemainsAvailable() {
        val tabs = WatchHomeNavTab.availableTabs(config, healthEnabled = true, notebookShown = true)
        assertEquals(listOf(WatchFaces, Notebook, Watches, Health, Notifications, Settings), tabs)
        assertEquals(listOf(WatchFaces, Notebook, Watches, Health), WatchHomeNavTab.barTabs(config, tabs))
        assertEquals(listOf(Notifications, Settings), tabs.drop(WatchHomeNavTab.barTabs(config, tabs).size))
    }

    @Test
    fun hiddenNotebookAndDisabledHealthStayOutOfNavigation() {
        val tabs = WatchHomeNavTab.availableTabs(config, healthEnabled = false, notebookShown = false)
        assertEquals(listOf(WatchFaces, Watches, Notifications, Settings), tabs)
        assertFalse(Index in tabs)
    }

    @Test
    fun userOrderAndSlotCountApplyToNotebook() {
        val chosen = config.copy(navBarTabs = listOf("Notebook", "Settings", "Health", "WatchFaces", "Watches", "Notifications"), navBarSlots = 3)
        val tabs = WatchHomeNavTab.availableTabs(chosen, healthEnabled = true, notebookShown = true)
        assertEquals(listOf(Notebook, Settings), WatchHomeNavTab.barTabs(chosen, tabs))
        assertEquals(listOf(Health, WatchFaces, Watches, Notifications), tabs.drop(2))
    }
}
