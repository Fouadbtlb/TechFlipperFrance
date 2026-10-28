import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useMemo, useRef, useState } from 'react';
import { FlatList, Pressable, StyleSheet, View, useColorScheme, useWindowDimensions } from 'react-native';
import MapView, { Marker, type Region } from 'react-native-maps';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DealCard } from '@/components/DealCard';
import { EmptyState, T } from '@/components/ui';
import { usePins } from '@/lib/queries';
import { useSession } from '@/lib/session';
import { radius, space, usePalette, zoneColor } from '@/lib/theme';
import type { Pin } from '@/lib/types';

const CARD_W = 300;
const GAP = 10;

function regionAround(lat: number, lng: number, km: number): Region {
  const d = Math.max(0.05, (km / 111) * 2.2);
  return { latitude: lat, longitude: lng, latitudeDelta: d, longitudeDelta: d * 1.4 };
}

export default function MapScreen() {
  const p = usePalette();
  const scheme = useColorScheme();
  const { width } = useWindowDimensions();
  const { me } = useSession();
  const q = usePins();
  const mapRef = useRef<MapView>(null);
  const listRef = useRef<FlatList<Pin>>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const home = me?.prefs.home_lat != null ? { latitude: me.prefs.home_lat, longitude: me.prefs.home_lng as number } : null;
  const initial = useMemo(
    () => (home ? regionAround(home.latitude, home.longitude, Math.min(me?.prefs.radius_km ?? 60, 150)) : undefined),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [home?.latitude, home?.longitude],
  );
  const pins = q.data?.items ?? [];

  function focus(i: number, scroll: boolean) {
    const pin = pins[i];
    if (!pin) return;
    setSelected(pin.uid);
    Haptics.selectionAsync();
    mapRef.current?.animateToRegion(
      { latitude: pin.lat, longitude: pin.lng, latitudeDelta: 0.25, longitudeDelta: 0.35 },
      350,
    );
    if (scroll) listRef.current?.scrollToIndex({ index: i, animated: true, viewOffset: (width - CARD_W) / 2 });
  }

  function recenter() {
    if (initial) mapRef.current?.animateToRegion(initial, 400);
    setSelected(null);
  }

  return (
    <View style={{ flex: 1, backgroundColor: p.bg }}>
      <MapView
        ref={mapRef}
        style={StyleSheet.absoluteFill}
        initialRegion={initial}
        userInterfaceStyle={scheme === 'light' ? 'light' : 'dark'}
        showsPointsOfInterests={false}
        toolbarEnabled={false}
        onPress={() => setSelected(null)}>
        {home ? (
          <Marker coordinate={home} anchor={{ x: 0.5, y: 0.5 }} tracksViewChanges={false}>
            <View style={[s.home, { backgroundColor: p.text, borderColor: p.bg }]}>
              <Ionicons name="home" size={12} color={p.bg} />
            </View>
          </Marker>
        ) : null}
        {pins.map((pin, i) => {
          const on = pin.uid === selected;
          const c = zoneColor(p, pin.zone);
          return (
            <Marker
              key={`${pin.uid}-${on ? 1 : 0}`}
              coordinate={{ latitude: pin.lat, longitude: pin.lng }}
              anchor={{ x: 0.5, y: 1 }}
              tracksViewChanges={false}
              zIndex={on ? 1000 : Math.round(pin.net)}
              onPress={(e) => {
                e.stopPropagation();
                focus(i, true);
              }}>
              <View style={{ alignItems: 'center' }}>
                <View style={[s.pin, { backgroundColor: on ? p.text : c }]}>
                  <T v="small" style={{ color: on ? p.bg : '#04140A', fontWeight: '800', fontVariant: ['tabular-nums'] }}>
                    +{Math.round(pin.net)}€
                  </T>
                </View>
                <View style={[s.tail, { borderTopColor: on ? p.text : c }]} />
              </View>
            </Marker>
          );
        })}
      </MapView>

      <SafeAreaView edges={['top']} style={s.top} pointerEvents="box-none">
        <View style={[s.badge, { backgroundColor: p.surface, borderColor: p.border }]}>
          <Ionicons name="flash" size={14} color={p.profit} />
          <T v="small" style={{ fontWeight: '700' }}>
            {q.isLoading ? '…' : `${pins.length} affaire${pins.length > 1 ? 's' : ''}`}
          </T>
        </View>
        <Pressable
          accessibilityLabel="Recentrer"
          onPress={recenter}
          style={[s.fab, { backgroundColor: p.surface, borderColor: p.border }]}>
          <Ionicons name="locate" size={20} color={p.text} />
        </Pressable>
      </SafeAreaView>

      {!q.isLoading && pins.length === 0 ? (
        <View style={[s.emptyWrap, { backgroundColor: p.surface, borderColor: p.border }]}>
          <EmptyState icon="map-outline" title="Aucune affaire sur la carte" body="Élargis ton rayon dans les réglages." />
        </View>
      ) : null}

      <View style={s.carousel} pointerEvents="box-none">
        <FlatList
          ref={listRef}
          data={pins}
          horizontal
          keyExtractor={(x) => x.uid}
          showsHorizontalScrollIndicator={false}
          snapToInterval={CARD_W + GAP}
          decelerationRate="fast"
          contentContainerStyle={{ paddingHorizontal: (width - CARD_W) / 2, gap: GAP }}
          getItemLayout={(_, i) => ({ length: CARD_W + GAP, offset: (CARD_W + GAP) * i, index: i })}
          onMomentumScrollEnd={(e) => focus(Math.round(e.nativeEvent.contentOffset.x / (CARD_W + GAP)), false)}
          renderItem={({ item }) => (
            <View style={[s.cardShadow, item.uid === selected && { transform: [{ scale: 1.02 }] }]}>
              <DealCard deal={item.card} compact />
            </View>
          )}
        />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  top: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: space.lg,
    paddingTop: space.sm,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    height: 40,
    paddingHorizontal: space.lg,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
  },
  fab: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
  },
  pin: { paddingHorizontal: 8, height: 26, borderRadius: 13, justifyContent: 'center' },
  tail: {
    width: 0,
    height: 0,
    borderLeftWidth: 5,
    borderRightWidth: 5,
    borderTopWidth: 6,
    borderLeftColor: 'transparent',
    borderRightColor: 'transparent',
  },
  home: { width: 24, height: 24, borderRadius: 12, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  carousel: { position: 'absolute', bottom: space.lg, left: 0, right: 0 },
  cardShadow: {
    shadowColor: '#000',
    shadowOpacity: 0.25,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 6,
  },
  emptyWrap: {
    position: 'absolute',
    left: space.xl,
    right: space.xl,
    top: '30%',
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
  },
});
