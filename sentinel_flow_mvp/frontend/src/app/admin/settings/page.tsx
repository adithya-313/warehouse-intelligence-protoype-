import SettingsDashboard from '@/components/admin/SettingsDashboard';

export const metadata = {
  title: 'Tenant Settings | Sentinel Flow',
  description: 'Configure WhatsApp, UPI, and security settings for your pharmacy tenant.',
};

export default function SettingsPage() {
  return <SettingsDashboard />;
}
