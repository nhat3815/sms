plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
}

subprojects {
    tasks.configureEach {
        if (name.contains("Dex", ignoreCase = true) || name.contains("package", ignoreCase = true) || name.contains("assemble", ignoreCase = true) || name.contains("Resources", ignoreCase = true)) {
            doFirst {
                layout.buildDirectory.asFile.get().walkBottomUp().filter { it.name.startsWith("._") }.forEach { it.delete() }
            }
        }
    }
}

