/**
 * Tipos de dominio compartidos (UI ↔ servicios ↔ API).
 * Para tipos generados desde el esquema usa `npm run db:types`
 * (genera `src/lib/supabase/database.types.ts`).
 */

export type MembershipTier = "silver" | "gold" | "platinum" | "signature";
export type MembershipStatus = "active" | "suspended" | "expired" | "cancelled";
export type ReservationStatus =
  | "pending"
  | "confirmed"
  | "changed"
  | "cancelled"
  | "completed";
export type Channel = "web" | "whatsapp" | "email";
export type ConversationStatus = "open" | "bot" | "assigned" | "resolved" | "closed";
export type MessageRole = "member" | "assistant" | "agent" | "system";
export type TicketStatus = "new" | "open" | "pending" | "escalated" | "resolved" | "closed";
export type TicketPriority = "low" | "medium" | "high" | "urgent";
export type TicketCategory =
  | "reservation"
  | "cancellation"
  | "billing"
  | "benefits"
  | "complaint"
  | "general";
export type OpportunityStage =
  | "detected"
  | "qualified"
  | "contacted"
  | "won"
  | "lost";

export interface Member {
  id: string;
  membership_no: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  locale: string;
}

export interface Membership {
  id: string;
  member_id: string;
  tier: MembershipTier;
  status: MembershipStatus;
  weeks_per_year: number;
  points_balance: number;
  start_date: string;
  end_date: string | null;
}

export interface Reservation {
  id: string;
  member_id: string;
  resort_name: string;
  room_type: string | null;
  check_in: string;
  check_out: string;
  guests: number;
  status: ReservationStatus;
  confirmation_code: string | null;
}

export interface ChatMessage {
  id?: string;
  role: MessageRole;
  content: string;
  created_at?: string;
}

/** Resultado de la clasificación de intención de un mensaje del socio. */
export interface IntentClassification {
  intent:
    | "reservation_change"
    | "cancellation"
    | "billing"
    | "benefits"
    | "faq"
    | "complaint"
    | "sales_lead"
    | "other";
  sentiment: "positive" | "neutral" | "negative";
  urgency: "low" | "medium" | "high";
  requires_human: boolean;
  sales_signal: {
    detected: boolean;
    product: string | null;
    confidence: number;
  };
}

/** Sesión del socio derivada de la cookie firmada. */
export interface MemberSession {
  member_id: string;
  membership_no: string;
  full_name: string;
  iat: number;
  exp: number;
}
