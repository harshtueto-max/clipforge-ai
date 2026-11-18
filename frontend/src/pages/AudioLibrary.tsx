import { FileAudio, Music2, Trash2, Upload, Volume2 } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { api, errMsg } from '../api';
import { PreviewButton, useAudioPreview } from '../components/AudioPreview';
import { PageHeader } from '../components/PageHeader';
import { Badge, Button, ConfirmDialog, EmptyState, ErrorState, Field, IconButton, inputCls, LoadingBlock, Modal, ProgressBar, Segmented, Select } from '../components/ui';
import { fmtBytes, fmtDur, titleCase } from '../lib/format';
import { useFetch } from '../lib/hooks';
import { toast } from '../stores/toast';
import type { AudioAsset } from '../types';

export function AudioLibraryPage() {
  const assets = useFetch(() => api.audio(), []);
  const cats = useFetch(() => api.audioCategories(), []);
  const [kind, setKind] = useState<'music' | 'sfx'>('music');
  const [importOpen, setImportOpen] = useState(false);
  const [del, setDel] = useState<AudioAsset | null>(null);
  const stop = useAudioPreview((s) => s.stop);
  useEffect(() => () => stop(), [stop]);
  const grouped = useMemo(() => {
    const g: Record<string, AudioAsset[]> = {};
    for (const a of assets.data ?? []) if (a.kind === kind) (g[a.category] ??= []).push(a);
    return g;
  }, [assets.data, kind]);
  const doDelete = async () => {
    if (!del) return;
    try {
      await api.deleteAudio(del.id);
      toast.success('Audio deleted', del.name);
      await assets.reload(true);
    } catch (e) {
      toast.error('Delete failed', errMsg(e));
    }
  };
  return (
    <div>
      <PageHeader
        title="Audio Library"
        subtitle="Royalty-free music beds and sound effects available to every clip. Import your own (with rights)."
        actions={
          <Button variant="primary" size="md" icon={<Upload className="h-4 w-4" />} onClick={() => setImportOpen(true)}>
            Import audio
          </Button>
        }
      >
        <div className="mt-3">
          <Segmented
            value={kind}
            onChange={setKind}
            options={[
              { value: 'music', label: <span className="flex items-center gap-1.5"><Music2 className="h-3.5 w-3.5" /> Music ({(assets.data ?? []).filter((a) => a.kind === 'music').length})</span> },
              { value: 'sfx', label: <span className="flex items-center gap-1.5"><Volume2 className="h-3.5 w-3.5" /> Sound effects ({(assets.data ?? []).filter((a) => a.kind === 'sfx').length})</span> },
            ]}
          />
        </div>
      </PageHeader>
      <div className="p-6">
        {assets.loading && !assets.data ? (
          <LoadingBlock />
        ) : assets.error ? (
          <ErrorState message={assets.error} onRetry={() => assets.reload()} />
        ) : Object.keys(grouped).length === 0 ? (
          <EmptyState icon={<FileAudio className="h-7 w-7" />} title={`No ${kind === 'music' ? 'music' : 'sound effects'} yet`} action={<Button onClick={() => setImportOpen(true)}>Import audio</Button>} />
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
            {Object.entries(grouped).map(([cat, list]) => (
              <section key={cat} className="rounded-lg border border-ink-600 bg-ink-800">
                <header className="flex h-9 items-center justify-between border-b border-ink-600 px-3">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-200">{titleCase(cat)}</h3>
                  <span className="text-2xs text-ink-400">{list.length}</span>
                </header>
                <div className="divide-y divide-ink-650">
                  {list.map((a) => (
                    <div key={a.id} className="flex items-center gap-2 px-2.5 py-2">
                      <PreviewButton id={a.id} url={a.url} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate text-xs text-ink-50">{a.name}</span>
                          {a.origin === 'user' ? <Badge tone="violet">imported</Badge> : <Badge>built-in</Badge>}
                        </div>
                        <div className="truncate text-[10px] text-ink-400" title={a.license}>
                          {fmtDur(a.duration)}
                          {a.bpm ? ` · ${Math.round(a.bpm)} BPM` : ''} · {a.license || 'No license note'}
                        </div>
                      </div>
                      {a.origin === 'user' && (
                        <IconButton title="Delete" onClick={() => setDel(a)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </IconButton>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
      <ImportAudioModal open={importOpen} onClose={() => setImportOpen(false)} cats={cats.data} defaultKind={kind} onDone={() => assets.reload(true)} />
      <ConfirmDialog open={!!del} onClose={() => setDel(null)} title="Delete audio" danger confirmLabel="Delete" message={<>Delete <b>{del?.name}</b>? Clips that use it will render without it.</>} onConfirm={doDelete} />
    </div>
  );
}

function ImportAudioModal({ open, onClose, cats, defaultKind, onDone }: { open: boolean; onClose: () => void; cats: { music: string[]; sfx: string[] } | null; defaultKind: 'music' | 'sfx'; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<'music' | 'sfx'>(defaultKind);
  const [category, setCategory] = useState('');
  const [name, setName] = useState('');
  const [license, setLicense] = useState('');
  const [rights, setRights] = useState(false);
  const [prog, setProg] = useState<number | null>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (open) {
      setFile(null);
      setKind(defaultKind);
      setName('');
      setLicense('');
      setRights(false);
      setProg(null);
    }
  }, [open, defaultKind]);
  const options = (kind === 'music' ? cats?.music : cats?.sfx) ?? [];
  useEffect(() => {
    if (options.length && !options.includes(category)) setCategory(options[0]);
  }, [options, category]);
  const submit = async () => {
    if (!file) return;
    setProg(0);
    try {
      const h = api.importAudio(file, { kind, category, name: name.trim() || undefined, license_note: license.trim() }, (l, t) => setProg(t ? l / t : 0));
      const a = await h.promise;
      toast.success('Audio imported', a.name);
      onDone();
      onClose();
    } catch (e) {
      toast.error('Import failed', errMsg(e));
      setProg(null);
    }
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Import audio"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!file || !rights || prog !== null} loading={prog !== null} onClick={submit}>
            Import
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Button icon={<Upload className="h-3.5 w-3.5" />} onClick={() => input.current?.click()}>
            Choose file
          </Button>
          <span className="truncate text-xs text-ink-200">{file ? `${file.name} · ${fmtBytes(file.size)}` : 'MP3, WAV, M4A, AAC, FLAC, OGG, OPUS (max 500 MB)'}</span>
          <input
            ref={input}
            type="file"
            accept="audio/*,.mp3,.wav,.m4a,.aac,.flac,.ogg,.opus"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              if (f && !name) setName(f.name.replace(/\.[^.]+$/, ''));
            }}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Type">
            <Segmented value={kind} onChange={setKind} options={[{ value: 'music', label: 'Music' }, { value: 'sfx', label: 'SFX' }]} />
          </Field>
          <Field label="Category">
            <Select value={category} onChange={setCategory} options={options.map((c) => ({ value: c, label: titleCase(c) }))} />
          </Field>
        </div>
        <Field label="Name">
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
        </Field>
        <Field label="License / source note" hint="e.g. “Purchased from …, license #123” or “Own composition”">
          <input className={inputCls} value={license} onChange={(e) => setLicense(e.target.value)} maxLength={300} />
        </Field>
        <label className="flex cursor-pointer items-start gap-2 text-xs text-ink-100">
          <input type="checkbox" className="mt-0.5 accent-amber-500" checked={rights} onChange={(e) => setRights(e.target.checked)} />I own this audio or have the rights to use it in my videos. (Required)
        </label>
        {prog !== null && <ProgressBar value={prog} />}
      </div>
    </Modal>
  );
}
