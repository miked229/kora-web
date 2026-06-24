import type { Metadata } from "next";
import { Inter, Playfair_Display } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const playfair = Playfair_Display({
  subsets: ["latin"],
  variable: "--font-playfair",
  weight: ["500", "600", "700"],
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000"),
  title: {
    default: "Member Concierge AI — Atención premium de membresías vacacionales",
    template: "%s · Member Concierge AI",
  },
  description:
    "Plataforma premium de atención automatizada para socios de membresías vacacionales: chat IA 24/7, reservaciones, beneficios y soporte omnicanal.",
  openGraph: {
    type: "website",
    locale: "es_MX",
    title: "Member Concierge AI",
    description:
      "El concierge de tu membresía vacacional, disponible 24/7. Reservaciones, beneficios y soporte instantáneo con IA.",
  },
  robots: { index: true, follow: true },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es" className={`${inter.variable} ${playfair.variable}`}>
      <head>
        {/* Preconexión al CDN de imágenes para acelerar el hero premium. */}
        <link rel="preconnect" href="https://images.unsplash.com" crossOrigin="" />
        <link rel="dns-prefetch" href="https://images.unsplash.com" />
      </head>
      <body>{children}</body>
    </html>
  );
}
