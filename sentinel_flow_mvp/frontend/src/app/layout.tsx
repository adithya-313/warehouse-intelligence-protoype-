import './globals.css';
import type { Metadata } from 'next';
import { Inter } from 'next/font/google';

const inter = Inter({ subsets: ['latin'], display: 'swap' });

export const metadata: Metadata = {
  title: 'Sentinel POS',
  description: 'Next-Gen Pharmacy POS',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${inter.className} font-sans antialiased bg-[#fdfbfb] text-slate-900 overflow-x-hidden min-h-screen`}>
        {children}
      </body>
    </html>
  );
}
