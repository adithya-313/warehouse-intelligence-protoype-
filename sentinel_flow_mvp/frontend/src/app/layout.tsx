import './globals.css';
import type { Metadata } from 'next';
import GlobalCursor from '@/components/GlobalCursor';

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
      <body className="font-sans antialiased bg-[#fdfbfb] text-slate-900 cursor-none overflow-hidden w-screen h-screen">
        <GlobalCursor />
        {children}
      </body>
    </html>
  );
}
