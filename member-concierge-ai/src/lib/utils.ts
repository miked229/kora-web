import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Combina clases de Tailwind resolviendo conflictos. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Formatea moneda en MXN por defecto. */
export function formatCurrency(value: number, currency = "MXN", locale = "es-MX") {
  return new Intl.NumberFormat(locale, { style: "currency", currency }).format(value);
}

/** Formatea una fecha ISO a formato legible en español. */
export function formatDate(iso: string, locale = "es-MX") {
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "long",
    year: "numeric",
  }).format(new Date(iso));
}

/** Respuesta JSON de error estandarizada. */
export function jsonError(message: string, status = 400, extra?: Record<string, unknown>) {
  return Response.json({ error: message, ...extra }, { status });
}

/** Respuesta JSON de éxito estandarizada. */
export function jsonOk<T>(data: T, status = 200) {
  return Response.json({ data }, { status });
}
