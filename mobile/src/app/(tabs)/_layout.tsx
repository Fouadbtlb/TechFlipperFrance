import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router/js-tabs';
import { StyleSheet } from 'react-native';

import { usePalette } from '@/lib/theme';

export default function TabsLayout() {
  const p = usePalette();
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: p.text,
        tabBarInactiveTintColor: p.textFaint,
        tabBarStyle: { backgroundColor: p.bg, borderTopColor: p.border, borderTopWidth: StyleSheet.hairlineWidth },
        tabBarLabelStyle: { fontSize: 11, fontWeight: '600' },
      }}>
      <Tabs.Screen
        name="index"
        options={{
          title: 'Affaires',
          tabBarIcon: ({ color, focused }) => <Ionicons name={focused ? 'flash' : 'flash-outline'} size={22} color={color as string} />,
        }}
      />
      <Tabs.Screen
        name="map"
        options={{
          title: 'Carte',
          tabBarIcon: ({ color, focused }) => <Ionicons name={focused ? 'map' : 'map-outline'} size={22} color={color as string} />,
        }}
      />
      <Tabs.Screen
        name="saved"
        options={{
          title: 'Favoris',
          tabBarIcon: ({ color, focused }) => <Ionicons name={focused ? 'heart' : 'heart-outline'} size={22} color={color as string} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Réglages',
          tabBarIcon: ({ color, focused }) => (
            <Ionicons name={focused ? 'options' : 'options-outline'} size={22} color={color as string} />
          ),
        }}
      />
    </Tabs>
  );
}
