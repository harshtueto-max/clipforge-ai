import { FolderOpen, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api, errMsg } from '../api';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import type { ExportSettings } from '../types';
import { DEFAULT_EXPORT } from '../types';
import { Button, Field, IconButton, inputCls, Modal, Select, Toggle } from './ui';

export function ExportSettingsForm({ value, onChange }: { value: ExportSettings; onChange: (v: ExportSettings) => void }) {
  const settings = useSettings((s) => s.settings);
  const set = <K extends keyof ExportSettings>(k: K, v: ExportSettings[K]) => onChange({ ...value, [k]: v });
  const pickDir = async () => {
    try {
      const r = await api.dialog('folder', 'Choose export folder');
      if (r.path) set('output_dir', r.path);
    } catch (e) {
      toast.error('Folder dialog failed', errMsg(e));
    }
  };
  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label="Resolution">
        <Select value={value.resolution} onChange={(v) => set('resolution', v)} options={[{ value: '720p', label: '720p' }, { value: '1080p', label: '1080p (recommended)' }, { value: '4k', label: '4K' }]} />
      </Field>
      <Field label="Frame rate">
        <Select value={value.fps} onChange={(v) => set('fps', v)} options={([24, 25, 30, 50, 60] as const).map((f) => ({ value: f, label: `${f} fps` }))} />
      </Field>
      <Field label="Codec">
        <Select value={value.codec} onChange={(v) => set('codec', v)} options={[{ value: 'h264', label: 'H.264 (most compatible)' }, { value: 'h265', label: 'H.265 / HEVC (smaller)' }]} />
      </Field>
      <Field label="Quality">
        <Select value={value.quality} onChange={(v) => set('quality', v)} options={[{ value: 'high', label: 'High' }, { value: 'balanced', label: 'Balanced' }, { value: 'small', label: 'Small file' }]} />
      </Field>
      <Field label="Video bitrate (kbps)" hint="Leave empty for quality-based encoding">
        <input
          className={inputCls}
          type="number"
          min={500}
          max={200000}
          placeholder="Auto"
          value={value.bitrate_kbps ?? ''}
          onChange={(e) => set('bitrate_kbps', e.target.value ? Number(e.target.value) : null)}
        />
      </Field>
      <Field label="Audio bitrate">
        <Select value={value.audio_bitrate_kbps} onChange={(v) => set('audio_bitrate_kbps', v)} options={[128, 160, 192, 256, 320].map((b) => ({ value: b, label: `${b} kbps` }))} />
      </Field>
      <Field label="Output folder" className="col-span-2">
        <div className="flex gap-1.5">
          <input className={inputCls} placeholder={settings?.exports_dir ?? 'Default exports folder'} value={value.output_dir ?? ''} onChange={(e) => set('output_dir', e.target.value || null)} />
          <Button size="sm" variant="subtle" icon={<FolderOpen className="h-3.5 w-3.5" />} onClick={pickDir}>
            Browse
          </Button>
          {value.output_dir && (
            <IconButton title="Use default folder" onClick={() => set('output_dir', null)}>
              <X className="h-3.5 w-3.5" />
            </IconButton>
          )}
        </div>
      </Field>
      <div className="col-span-2">
        <Toggle checked={value.captions} onChange={(v) => set('captions', v)} label="Burn in captions" />
      </div>
    </div>
  );
}

export function ExportDialog({ open, onClose, clipIds, initial, onQueued }: { open: boolean; onClose: () => void; clipIds: string[]; initial?: Partial<ExportSettings>; onQueued?: () => void }) {
  const [value, setValue] = useState<ExportSettings>({ ...DEFAULT_EXPORT, ...initial });
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) setValue({ ...DEFAULT_EXPORT, ...initial });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const submit = async () => {
    setBusy(true);
    try {
      if (clipIds.length === 1) await api.exportClip(clipIds[0], value);
      else await api.batch(clipIds, 'export', value);
      toast.success(clipIds.length === 1 ? 'Export queued' : `${clipIds.length} exports queued`, 'Progress is shown in the processing queue.');
      onQueued?.();
      onClose();
    } catch (e) {
      toast.error('Export failed to start', errMsg(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={clipIds.length === 1 ? 'Export clip' : `Export ${clipIds.length} clips`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} onClick={submit} disabled={!clipIds.length}>
            Start export
          </Button>
        </>
      }
    >
      <ExportSettingsForm value={value} onChange={setValue} />
    </Modal>
  );
}
