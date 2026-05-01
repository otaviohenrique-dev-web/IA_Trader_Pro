import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css"; // 🚀 O CSS ESTÁ DE VOLTA!

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin", "latin-ext"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin", "latin-ext"],
});

// AÇÃO: Atualização de Metadados + Open Graph (WhatsApp)
export const metadata = {
  // Resolve o aviso do Next.js. Se não houver variável de ambiente, usa o localhost.
  // IMPORTANTE: Na Vercel, configure a variável NEXT_PUBLIC_SITE_URL com o seu domínio final.
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"),
  
  title: "Sniper Engine v3.0 • Neural ONNX Terminal [BTC/USDT]",
  description: "Advanced Algorithmic Execution System | Gemini Market Sentinel.",
  
  openGraph: {
    title: "IA Trader Pro v3.0 | Sniper Neural Online 🚀",
    description: "Monitoramento em tempo real via ONNX Runtime e Sentinela de Notícias Gemini. Clique para ver a IA em ação no par BTC/USDT.",
    url: '/',
    siteName: 'IA Trader Pro',
    images: [
      {
        url: '/og-image.png', // A imagem de 10KB que geramos
        width: 1200,
        height: 630,
        alt: 'Dashboard IA Trader Pro',
      },
    ],
    locale: 'pt_BR',
    type: 'website',
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