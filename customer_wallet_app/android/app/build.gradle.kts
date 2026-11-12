plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

val teamStore = System.getenv("KWIKPAY_ANDROID_KEYSTORE")
val teamStorePassword = System.getenv("KWIKPAY_ANDROID_STORE_PASSWORD")
val teamKeyPassword = System.getenv("KWIKPAY_ANDROID_KEY_PASSWORD")
if (gradle.startParameter.taskNames.any { it.contains("release", ignoreCase = true) } &&
    listOf(teamStore, teamStorePassword, teamKeyPassword).any { it.isNullOrBlank() }) {
    throw GradleException("Team release signing credentials are required.")
}

android {
    signingConfigs {
        create("teamRelease") {
            if (!teamStore.isNullOrBlank()) storeFile = file(teamStore)
            storePassword = teamStorePassword
            keyAlias = "kwikpay-team-v1"
            keyPassword = teamKeyPassword
        }
    }
    namespace = "za.co.kwikpay.kwikpay_customer"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "za.co.kwikpay.kwikpay_customer"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("teamRelease")
        }
    }
}

flutter {
    source = "../.."
}
