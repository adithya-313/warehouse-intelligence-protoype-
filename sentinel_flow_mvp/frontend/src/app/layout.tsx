import type { Metadata } from 'next';
import { Toaster } from 'sonner';
import './globals.css';

export const metadata: Metadata = {
  title: 'Sentinel-Flow | Supply Chain Intelligence',
  description: 'LoRA Orchestration & Supply Chain Intelligence Platform',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-mesh-gradient bg-slate-950">
        <Toaster position="top-right" theme="dark" toastOptions={{
          style: { background: 'rgba(15, 23, 42, 0.9)', backdropFilter: 'blur(10px)', border: '1px solid rgba(255,255,255,0.1)', color: 'white' }
        }} />
        <div className="relative min-h-screen">
          <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_50%_30%_at_50%_0%,rgba(99,102,241,0.06),transparent)]" />
          <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_40%_25%_at_80%_90%,rgba(20,184,166,0.05),transparent)]" />
          {children}
        </div>
      </body>
    </html>
  );
}
