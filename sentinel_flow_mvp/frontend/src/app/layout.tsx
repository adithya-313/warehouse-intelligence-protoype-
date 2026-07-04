import './globals.css';
import type { Metadata } from 'next';

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
      <body className="font-sans antialiased bg-[#fdfbfb] text-slate-900 overflow-x-hidden min-h-screen">
        {children}
      </body>
    </html>
  );
}
