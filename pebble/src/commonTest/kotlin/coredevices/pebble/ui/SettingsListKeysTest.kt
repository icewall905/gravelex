package coredevices.pebble.ui

import kotlin.test.Test
import kotlin.test.assertEquals

class SettingsListKeysTest {
    @Test
    fun identicalRowsGetDifferentKeys() {
        val setting = setting(Section.Apps, "Configure Appstore Sources")

        val keys = settingsListKeys(listOf(setting, setting))

        assertEquals(2, keys.toSet().size)
        assertEquals(settingsListKeys(listOf(setting)).single(), keys.first())
    }

    @Test
    fun equalTitlesInDifferentSectionsKeepTheirKeysWhenFiltered() {
        val apps = setting(Section.Apps, "Advanced")
        val support = setting(Section.Support, "Advanced")

        val keys = settingsListKeys(listOf(apps, support))

        assertEquals(2, keys.toSet().size)
        assertEquals(settingsListKeys(listOf(support)).single(), keys.last())
    }

    private fun setting(section: Section, title: String) = SettingsItem(
        title = title,
        topLevelType = TopLevelType.Phone,
        section = section,
        item = {},
        isDebugSetting = false,
    )
}
