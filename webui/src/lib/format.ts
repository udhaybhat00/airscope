/** Display helpers mirroring the TUI iconography (ui/icons.py). */

export function signalTier(dbm: number | null | undefined): string {
  if (dbm === null || dbm === undefined) return '…';
  if (dbm < -80) return '▁';
  if (dbm < -70) return '▂';
  if (dbm < -60) return '▃';
  if (dbm < -50) return '▅';
  return '▇';
}

const ENC_ICON: Record<string, string> = {
  OPEN: '○',
  WEP: '◐',
  WPA: '⬢',
  WPA2: '⬣',
  WPA3: '◆',
  OWE: '◇'
};

export function encIcon(encryption: string): string {
  const upper = (encryption || 'UNKNOWN').toUpperCase();
  if (upper.includes('WPA3') && upper.includes('WPA2')) return '◆→2';
  for (const [key, icon] of Object.entries(ENC_ICON)) {
    if (upper.includes(key)) return icon;
  }
  return '?';
}

export function encClass(encryption: string): string {
  const upper = (encryption || '').toUpperCase();
  if (upper === 'OPEN' || upper === 'UNKNOWN' || upper === '') return 'muted';
  if (upper === 'WEP' || upper.includes('WPA2')) return 'attackable';
  if (upper.includes('WPA3') && upper.includes('WPA2')) return 'mixed';
  if (upper === 'WPA3') return 'outofscope';
  if (upper === 'OWE') return 'interesting';
  if (upper === 'WPA') return 'outofscope';
  return 'muted';
}

const ENC_SUFFIX: Record<string, string> = {
  WPA2: ' · Password protected',
  WPA: ' · Password protected',
  WEP: ' · Weak encryption',
  OPEN: ' · No password',
  WPA3: ' · Modern security',
  OWE: ' · Open (enhanced)',
};

export function encSuffix(encryption: string): string {
  const upper = (encryption || '').toUpperCase();
  if (upper.includes('WPA3') && upper.includes('WPA2')) return ' · Mixed mode';
  for (const [key, suffix] of Object.entries(ENC_SUFFIX)) {
    if (upper.includes(key)) return suffix;
  }
  return '';
}
