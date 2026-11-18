import { Film, FolderOpen, ImageOff } from 'lucide-react';
import { useState } from 'react';
import { apiUrl } from '../api';
import { cx } from '../lib/format';

export function Thumb({ src, alt, className, iconSize = 'h-6 w-6', children }: { src: string | null; alt: string; className?: string; iconSize?: string; children?: React.ReactNode }) {
  const [failed, setFailed] = useState(false);
  const resolved = src ? apiUrl(src) : null;
  return (
    <div className={cx('relative overflow-hidden bg-ink-950', className)}>
      {resolved && !failed ? (
        <img src={resolved} alt={alt} loading="lazy" className="h-full w-full object-cover" onError={() => setFailed(true)} />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-ink-500">{resolved ? <ImageOff className={iconSize} /> : <Film className={iconSize} />}</div>
      )}
      {children}
    </div>
  );
}

export function FolderIcon() {
  return <FolderOpen className="h-3.5 w-3.5" />;
}
