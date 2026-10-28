import type { ExpoConfig } from 'expo/config';

// Public, non-secret build settings come from EXPO_PUBLIC_* env vars (see .env.example).
// Nothing secret belongs here: everything in the app binary is readable by anyone.
const env = process.env;

const config: ExpoConfig = {
  name: 'TechFlip',
  slug: 'techflip',
  scheme: 'techflip',
  version: '1.0.0',
  orientation: 'portrait',
  icon: './assets/icon.png',
  userInterfaceStyle: 'automatic',
  backgroundColor: '#0B0D10',
  ios: {
    bundleIdentifier: env.EXPO_PUBLIC_IOS_BUNDLE_ID ?? 'fr.techflip.app',
    supportsTablet: false,
    entitlements: {
      // App Attest keys from a production build are only valid in production.
      'com.apple.developer.devicecheck.appattest-environment':
        env.EXPO_PUBLIC_APP_ATTEST_ENV ?? 'production',
    },
    infoPlist: {
      ITSAppUsesNonExemptEncryption: false,
    },
  },
  android: {
    package: env.EXPO_PUBLIC_ANDROID_PACKAGE ?? 'fr.techflip.app',
    adaptiveIcon: {
      backgroundColor: '#0B0D10',
      foregroundImage: './assets/android-icon-foreground.png',
      backgroundImage: './assets/android-icon-background.png',
      monochromeImage: './assets/android-icon-monochrome.png',
    },
    // No backups: tokens must not follow an adb backup onto another device.
    allowBackup: false,
    predictiveBackGestureEnabled: false,
  },
  plugins: [
    'expo-router',
    'expo-secure-store',
    'expo-image',
    'expo-system-ui',
    [
      'expo-location',
      {
        locationWhenInUsePermission:
          "TechFlip utilise ta position pour calculer la distance et le coût d'aller chercher chaque affaire.",
      },
    ],
    ['expo-notifications', { color: '#2BD576', defaultChannel: 'deals' }],
    [
      'react-native-maps',
      // Apple Maps on iOS needs no key. Android needs a Google Maps SDK key,
      // restricted to this package + signing certificate in Google Cloud.
      { androidGoogleMapsApiKey: env.EXPO_PUBLIC_ANDROID_MAPS_KEY ?? '' },
    ],
  ],
  experiments: { typedRoutes: true },
  extra: {
    apiUrl: env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000',
    revenuecatIosKey: env.EXPO_PUBLIC_RC_IOS_KEY ?? '',
    revenuecatAndroidKey: env.EXPO_PUBLIC_RC_ANDROID_KEY ?? '',
    playCloudProjectNumber: env.EXPO_PUBLIC_PLAY_CLOUD_PROJECT ?? '',
    // Simulators/emulators have no App Attest / Play Integrity: dev builds talk
    // to a backend running ATTEST_MODE=off. Never true in a store build.
    insecureDevAuth: env.EXPO_PUBLIC_INSECURE_DEV_AUTH === '1',
    termsUrl: env.EXPO_PUBLIC_TERMS_URL ?? 'https://techflip.fr/cgu',
    privacyUrl: env.EXPO_PUBLIC_PRIVACY_URL ?? 'https://techflip.fr/confidentialite',
    eas: { projectId: env.EXPO_PUBLIC_EAS_PROJECT_ID ?? '' },
  },
};

export default config;
