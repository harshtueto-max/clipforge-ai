import { Check, Save, Search, Undo2 } from 'lucide-react';
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { api, errMsg } from '../api';
import { cx, fmtTime } from '../lib/format';
import { useFetch } from '../lib/hooks';
import { toast } from '../stores/toast';
import type { Sentence, Word } from '../types';
import { Button, EmptyState, ErrorState, inputCls, LoadingBlock } from './ui';

const SPK_COLORS = ['#ffbf47', '#7cc4ff', '#c084fc', '#4ade80', '#fb7185', '#2dd4bf', '#fdba74', '#a3e635'];

export function TranscriptView({ projectId, currentTime, onSeek }: { projectId: string; currentTime: number; onSeek: (t: number) => void }) {
  const q = useFetch(() => api.transcript(projectId), [projectId]);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [editing, setEditing] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [filter, setFilter] = useState('');
  const [follow, setFollow] = useState(true);
  const container = useRef<HTMLDivElement>(null);

  const words = q.data?.words ?? [];
  const activeIdx = useMemo(() => {
    if (!words.length) return -1;
    let lo = 0;
    let hi = words.length - 1;
    while (lo <= hi) {
      const m = (lo + hi) >> 1;
      if (currentTime < words[m].s) hi = m - 1;
      else if (currentTime > words[m].e) lo = m + 1;
      else return m;
    }
    return -1;
  }, [words, currentTime]);

  useEffect(() => {
    if (!follow || activeIdx < 0 || !container.current) return;
    const el = container.current.querySelector<HTMLElement>(`[data-w="${activeIdx}"]`);
    if (!el) return;
    const c = container.current.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    if (r.top < c.top + 40 || r.bottom > c.bottom - 40) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [activeIdx, follow]);

  if (q.loading && !q.data) return <LoadingBlock label="Loading transcript…" />;
  if (q.error) return q.error.includes('not available') ? <EmptyState title="No transcript yet">Run the analysis to transcribe this video.</EmptyState> : <ErrorState message={q.error} onRetry={() => q.reload()} />;
  if (!q.data) return null;

  const sentences = q.data.sentences;
  const pending = Object.keys(edits).length;
  const save = async () => {
    setSaving(true);
    try {
      const r = await api.correctWords(projectId, Object.entries(edits).map(([i, w]) => ({ i: Number(i), w })));
      toast.success(`Saved ${r.updated} correction(s)`, 'Captions rebuilt from the transcript will use the corrected words.');
      setEdits({});
      await q.reload(true);
    } catch (e) {
      toast.error('Could not save corrections', errMsg(e));
    } finally {
      setSaving(false);
    }
  };
  const visible = filter.trim() ? sentences.filter((s) => s.text.toLowerCase().includes(filter.trim().toLowerCase())) : sentences;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-ink-600 px-3 py-2">
        <div className="relative w-56">
          <Search className="absolute left-2 top-2 h-3.5 w-3.5 text-ink-400" />
          <input className={`${inputCls} h-7 pl-7`} placeholder="Search transcript" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        <label className="flex items-center gap-1.5 text-2xs text-ink-200">
          <input type="checkbox" className="accent-amber-500" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Follow playback
        </label>
        <span className="text-2xs text-ink-300">
          {q.data.language} · {q.data.model} · {q.data.device ?? 'cpu'} · {words.length.toLocaleString()} words · click a word to seek, double-click to correct
        </span>
        <div className="flex-1" />
        {pending > 0 && (
          <>
            <Button size="xs" variant="ghost" icon={<Undo2 className="h-3 w-3" />} onClick={() => setEdits({})}>
              Discard
            </Button>
            <Button size="xs" variant="primary" icon={<Save className="h-3 w-3" />} loading={saving} onClick={save}>
              Save {pending} correction{pending > 1 ? 's' : ''}
            </Button>
          </>
        )}
      </div>
      <div ref={container} className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {visible.length === 0 && <div className="py-6 text-center text-xs text-ink-300">No matching sentences.</div>}
        {visible.map((s) => (
          <SentenceRow
            key={s.i}
            s={s}
            words={words}
            activeIdx={activeIdx >= s.w0 && activeIdx < s.w1 ? activeIdx : -1}
            edits={edits}
            editing={editing !== null && editing >= s.w0 && editing < s.w1 ? editing : null}
            onSeek={onSeek}
            onEdit={setEditing}
            onCommit={(i, w) => {
              setEditing(null);
              const orig = words[i]?.w;
              setEdits((prev) => {
                const n = { ...prev };
                if (!w.trim() || w.trim() === orig) delete n[i];
                else n[i] = w.trim();
                return n;
              });
            }}
          />
        ))}
      </div>
    </div>
  );
}

const SentenceRow = memo(function SentenceRow({ s, words, activeIdx, edits, editing, onSeek, onEdit, onCommit }: {
  s: Sentence; words: Word[]; activeIdx: number; edits: Record<number, string>; editing: number | null; onSeek: (t: number) => void; onEdit: (i: number | null) => void; onCommit: (i: number, w: string) => void;
}) {
  const spk = s.speaker ?? 0;
  return (
    <div className="group mb-2.5 flex gap-3">
      <button className="w-14 shrink-0 pt-0.5 text-left font-mono text-2xs text-ink-400 hover:text-amber-400" onClick={() => onSeek(s.s)}>
        {fmtTime(s.s)}
      </button>
      <div className="min-w-0 flex-1">
        <span className="mr-1.5 text-2xs font-semibold" style={{ color: SPK_COLORS[spk % SPK_COLORS.length] }}>
          S{spk + 1}
        </span>
        <span className="text-[13px] leading-relaxed text-ink-100">
          {Array.from({ length: s.w1 - s.w0 }, (_, k) => s.w0 + k).map((i) => {
            const w = words[i];
            if (!w) return null;
            if (editing === i) return <WordEditor key={i} initial={edits[i] ?? w.w} onDone={(v) => onCommit(i, v)} onCancel={() => onEdit(null)} />;
            const edited = edits[i] !== undefined;
            return (
              <span key={i}>
                <span
                  data-w={i}
                  onClick={() => onSeek(w.s)}
                  onDoubleClick={() => onEdit(i)}
                  title={`${fmtTime(w.s, true)} · confidence ${w.p !== undefined ? Math.round(w.p * 100) : '?'}%`}
                  className={cx(
                    'cursor-pointer rounded px-px hover:bg-ink-650',
                    i === activeIdx && 'bg-amber-500/25 text-amber-200',
                    edited && 'text-emerald-300 underline decoration-dotted',
                    w.p !== undefined && w.p < 0.5 && !edited && 'text-ink-300 decoration-red-400/60 underline decoration-wavy',
                  )}
                >
                  {edits[i] ?? w.w}
                </span>{' '}
              </span>
            );
          })}
        </span>
      </div>
    </div>
  );
});

function WordEditor({ initial, onDone, onCancel }: { initial: string; onDone: (v: string) => void; onCancel: () => void }) {
  const [v, setV] = useState(initial);
  return (
    <span className="inline-flex items-center gap-0.5 align-middle">
      <input
        autoFocus
        className="h-6 rounded border border-amber-500/70 bg-ink-900 px-1 text-xs text-ink-50 outline-none"
        style={{ width: Math.max(40, v.length * 8 + 16) }}
        value={v}
        maxLength={59}
        onChange={(e) => setV(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onDone(v);
          if (e.key === 'Escape') onCancel();
        }}
        onBlur={() => onDone(v)}
      />
      <Check className="h-3 w-3 text-emerald-400" />{' '}
    </span>
  );
}
