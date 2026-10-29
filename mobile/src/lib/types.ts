export type Zone = 'EASY' | 'MEDIUM' | 'HARD';
export type Mode = 'pickup' | 'ship' | 'none';
export type Risk = 'low' | 'medium' | 'high';

export type Category =
  | 'console' | 'pc' | 'gpu' | 'cpu' | 'laptop' | 'phone' | 'monitor' | 'parts' | 'accessory' | 'other';

export interface DealCard {
  uid: string;
  title: string;
  price: number;
  prev_price: number | null;
  value: number;
  net: number;
  zone: Zone;
  distance_km: number | null;
  logistics: number | null;
  mode: Mode;
  city: string | null;
  category: Category | null;
  thumb: string | null;
  published_at: string | null;
  first_seen: string | null;
  confidence: number | null;
  risk: Risk;
  lat: number | null;
  lng: number | null;
  source: string;
  shop: boolean;
  reliable: boolean;
  reposts: number;
  days_to_sell: number | null;
  gone?: boolean;
}

export interface Part {
  label: string;
  qty: number;
  value: number | null;
  source: 'owner' | 'sold' | 'learned' | 'blend' | 'seed' | 'ai' | 'unknown';
  n: number;
  condition: string;
}

export interface SellerFlag { level: 'risk' | 'warn'; text: string }

export interface Seller {
  known: boolean;
  name?: string | null;
  kind?: string | null;
  age_days?: number | null;
  rating?: number | null;
  reviews?: number | null;
  flags: SellerFlag[];
}

export interface DealDetail extends DealCard {
  url: string;
  images: string[];
  description: string;
  condition: string | null;
  department: string | null;
  method: 'parts' | 'parts+ai' | 'ai' | null;
  parts: Part[];
  photo_checked: boolean;
  photo_unverified: boolean;
  carrier_locked?: boolean;
  shippable: boolean;
  scam_score: number | null;
  seller: Seller | null;
  reasons: string[];
  price_history: { price: number; at: string }[];
  saved: boolean;
  floor: number | null;
  floor_net: number | null;
  negotiation: { max_price: number; opening: number | null; message: string; leverage: string | null } | null;
  feedback: Feedback;
}

export type Verdict = 'low' | 'fair' | 'high';

export interface Feedback {
  low: number;
  fair: number;
  high: number;
  mine: Verdict | null;
  my_resale: number | null;
}

export interface Prefs {
  home_lat: number | null;
  home_lng: number | null;
  home_label: string | null;
  radius_km: number | null;
  include_shipping: boolean;
  min_profit: number | null;
  categories: Category[];
  notify: boolean;
  notify_mode: 'instant' | 'daily';
}

export interface Me {
  id: string;
  prefs: Prefs;
  entitlement: { active: boolean; until: string | null; product: string | null };
}

export interface Teaser {
  count: number;
  best_net: number | null;
  near: number;
  by_category: Record<string, number>;
}

export interface Page<T> {
  total: number;
  items: T[];
  next_offset: number | null;
  counts?: { reliable: number; check: number };
}
export interface Pin { uid: string; lat: number; lng: number; net: number; zone: Zone; category: Category; card: DealCard }
