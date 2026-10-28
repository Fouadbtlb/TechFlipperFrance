import Constants from 'expo-constants';

type Extra = {
  apiUrl: string;
  revenuecatIosKey: string;
  revenuecatAndroidKey: string;
  playCloudProjectNumber: string;
  insecureDevAuth: boolean;
  termsUrl: string;
  privacyUrl: string;
  eas?: { projectId?: string };
};

export const config = (Constants.expoConfig?.extra ?? {}) as Extra;
