package com.anopticlabs.gravel.planner

import android.content.Intent
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

@Composable
internal fun WorkoutPlannerEntry() {
    val context = LocalContext.current
    TextButton(onClick = { context.startActivity(Intent(context, WorkoutPlannerActivity::class.java)) }) {
        Text("Workout planner")
    }
}
