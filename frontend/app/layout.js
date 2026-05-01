import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin", "latin-ext"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin", "latin-ext"],
});

export const metadata = {
  // A URL base que o Next.js usará para montar os links das imagens
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "https://iatraderpro-nine.vercel.app"),
  
  title: "Sniper Engine v3.0 • Neural ONNX Terminal [BTC/USDT]",
  description: "Advanced Algorithmic Execution System | Gemini Market Sentinel.",
  
  // Efeito Card WhatsApp / LinkedIn / Facebook
  openGraph: {
    title: "IA Trader Pro v3.0 | Sniper Neural Online 🚀",
    description: "Monitoramento em tempo real via ONNX Runtime e Sentinela de Notícias Gemini. Clique para ver a IA em ação no par BTC/USDT.",
    url: '/',
    siteName: 'IA Trader Pro',
    images: [
      {
        url: '/og-image.png',
        width: 1200,
        height: 630,
        alt: 'Dashboard IA Trader Pro',
      },
    ],
    locale: 'pt_BR',
    type: 'website',
  },

  // Efeito Card Twitter / X / Discord / Telegram
  twitter: {
    card: 'summary_large_image',
    title: "IA Trader Pro v3.0 | Sniper Neural Online 🚀",
    description: "Monitoramento em tempo real via ONNX Runtime e Sentinela de Notícias Gemini.",
    images: ['/og-image.png'],
  },

  icons: {
    icon: "/favicon.ico",
    shortcut: "/favicon.ico",
    apple: "/apple-touch-icon.png",
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="pt-BR">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}