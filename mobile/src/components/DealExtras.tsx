import * as Clipboard from 'expo-clipboard';
import * as Haptics from 'expo-haptics';
import { useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';

import { euros } from '@/lib/format';
import { useFeedback } from '@/lib/queries';
import { font, radius, space, usePalette } from '@/lib/theme';
import type { DealDetail, Verdict } from '@/lib/types';

import { Button, Chip, LedgerRow, SectionTitle, T } from './ui';

/** Opening offer, the price not to exceed, and a message ready to send. */
export function Negotiation({ n }: { n: NonNullable<DealDetail['negotiation']> }) {
  const p = usePalette();
  const [copied, setCopied] = useState(false);
  return (
    <>
      <SectionTitle>Négocier</SectionTitle>
      {n.opening ? <LedgerRow label="Offre d’ouverture" value={euros(n.opening)} /> : null}
      <LedgerRow label="Ton prix maximum" value={euros(n.max_price)} tone="profit" />
      <T v="small" color="faint">
        Au-delà, la marge passe sous ton seuil.
      </T>
      {n.leverage ? (
        <View style={[s.note, { borderLeftColor: p.brass }]}>
          <T v="small" color="brass">
            {n.leverage}
          </T>
        </View>
      ) : null}
      <View style={[s.message, { borderColor: p.border, backgroundColor: p.surface }]}>
        <T selectable>{n.message}</T>
      </View>
      <Button
        label={copied ? 'Message copié' : 'Copier le message'}
        kind="secondary"
        onPress={async () => {
          await Clipboard.setStringAsync(n.message);
          Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
          setCopied(true);
        }}
        style={{ marginTop: space.md }}
      />
    </>
  );
}

const VERDICTS: { key: Verdict; label: string }[] = [
  { key: 'low', label: 'Trop basse' },
  { key: 'fair', label: 'Juste' },
  { key: 'high', label: 'Trop haute' },
];

/**
 * Subscribers help keep the estimates honest: their verdicts nudge the value
 * (bounded, and only once several people agree) and the resale prices they
 * report count as real sales.
 */
export function EstimateFeedback({ d }: { d: DealDetail }) {
  const p = usePalette();
  const send = useFeedback(d.uid);
  const [resale, setResale] = useState(d.feedback.my_resale ? String(Math.round(d.feedback.my_resale)) : '');
  const [error, setError] = useState<string | null>(null);
  const f = d.feedback;
  const total = f.low + f.fair + f.high;

  async function saveResale() {
    const v = Number(resale.replace(',', '.'));
    if (!v || v <= 0) return;
    setError(null);
    try {
      await send.mutateAsync({ resale_price: v });
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    } catch (e: any) {
      setError(e?.message ?? 'Enregistrement impossible.');
    }
  }

  return (
    <>
      <SectionTitle>Ton avis sur l’estimation</SectionTitle>
      <T color="muted">{`Revente estimée : ${euros(d.value)}. Elle te paraît…`}</T>
      <View style={s.row}>
        {VERDICTS.map((v) => (
          <Chip key={v.key} label={v.label} soft active={f.mine === v.key} onPress={() => send.mutate({ verdict: v.key })} />
        ))}
      </View>
      {total > 0 ? (
        <T v="small" color="faint" style={{ marginTop: space.sm }}>
          {`${total} avis d’abonnés : ${f.fair} juste${f.fair > 1 ? 's' : ''}, ${f.high} trop haute${f.high > 1 ? 's' : ''}, ${f.low} trop basse${f.low > 1 ? 's' : ''}.`}
        </T>
      ) : null}

      <T v="strong" style={{ marginTop: space.xl }}>
        Tu l’as revendu ?
      </T>
      <T v="small" color="muted">
        Ton prix de revente compte comme une vraie vente et affine les estimations de tout le monde.
      </T>
      <View style={[s.input, { borderColor: p.border, backgroundColor: p.surface }]}>
        <TextInput
          value={resale}
          onChangeText={setResale}
          placeholder="Prix de revente"
          placeholderTextColor={p.textFaint}
          keyboardType="decimal-pad"
          style={[s.field, { color: p.text }]}
        />
        <T color="muted" style={{ paddingRight: space.md }}>
          €
        </T>
        <Button label={f.my_resale ? 'Mettre à jour' : 'Enregistrer'} kind="ghost" onPress={saveResale} loading={send.isPending} style={s.save} />
      </View>
      {error ? (
        <T v="small" color="warn">
          {error}
        </T>
      ) : f.my_resale ? (
        <T v="small" color="profit">{`Merci, revente à ${euros(f.my_resale)} enregistrée.`}</T>
      ) : null}
    </>
  );
}

const s = StyleSheet.create({
  note: { borderLeftWidth: 2, paddingLeft: space.md, paddingVertical: 2, marginTop: space.sm },
  message: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.md, padding: space.lg, marginTop: space.md },
  row: { flexDirection: 'row', gap: space.sm, marginTop: space.md, flexWrap: 'wrap' },
  input: {
    height: 52,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    alignItems: 'center',
    paddingLeft: space.lg,
    marginTop: space.md,
  },
  field: { flex: 1, fontSize: 16, fontFamily: font.sans, height: '100%' },
  save: { height: 40, paddingHorizontal: space.md },
});
