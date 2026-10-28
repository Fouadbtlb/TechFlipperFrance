import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router/js-tabs';
import { StyleSheet } from 'react-native';

import { font, usePalette } from '@/lib/theme';

export default function TabsLayout() {
  const p = usePalette();
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: p.accent,
        tabBarInactiveTintColor: p.textFaint,
        tabBarStyle: { backgroundColor: p.bg, borderTopColor: p.border, borderTopWidth: StyleSheet.hairlineWidth },
        tabBarLabelStyle: { fontFamily: font.sansBold, fontSize: 10.5, lineHeight: 14, letterSpacing: 1.1, textTransform: 'uppercase' },
      }}>
      <Tabs.Screen
        name="index"
        options={{
          title: 'Affaires',
          tabBarIcon: ({ color }) => <Ionicons name="reader-outline" size={21} color={color as string} />,
        }}
      />
      <Tabs.Screen
        name="map"
        options={{
          title: 'Carte',
          tabBarIcon: ({ color }) => <Ionicons name="map-outline" size={21} color={color as string} />,
        }}
      />
      <Tabs.Screen
        name="saved"
        options={{
          title: 'Favoris',
          tabBarIcon: ({ color }) => <Ionicons name="heart-outline" size={21} color={color as string} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Réglages',
          tabBarIcon: ({ color }) => <Ionicons name="options-outline" size={21} color={color as string} />,
        }}
      />
    </Tabs>
  );
}
