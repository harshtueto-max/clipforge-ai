import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, Check, ChevronDown, Copy, Download, Pencil, Play, RefreshCw, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiUrl } from '../api';
import { cx, fmtDur, fmtTime, titleCase } from '../lib/format';
import type { Clip } from '../types';
import { DIM_LABELS, SCORE_DIMENSIONS, TAG_LABELS } from '../types';
import { Thumb } from './Thumb';
import { Badge, Button, IconButton, Modal, ScoreBar, ScoreRing, StatusBadge } from './ui';

export interface ClipActions {
  onPreview: (c: Clip) => void;
  onStatus: (c: Clip, status: 'accepted' | 'rejected' | 'suggested') => void;
  onRegenerate: (c: Clip) => Promise<void>;
  onDuplicate: (c: Clip) => Promise<void>;
  onExport: (c: Clip) => void;
}

export function ClipCard({ clip, selected, onSelect, actions, onSeek }: { clip: Clip; selected: boolean; onSelect: (v: boolean) => void; actions: ClipActions; onSeek?: (t: number) => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  };
  const statusRing = clip.status === 'accepted' ? 'border-emerald-500/50' : clip.status === 'rejected' ? 'border-red-500/30 opacity-70' : 'border-ink-600';
  return (
    <div className={cx('flex flex-col overflow-hidden rounded-lg border bg-ink-800 transition-colors', statusRing, selected && 'ring-1 ring-amber-500/70')}>
      <div className="flex gap-3 p-3">
        <div className="relative w-[148px] shrink-0">
          <Thumb src={clip.has_thumbnail ? `/api/clips/${clip.id}/thumbnail?v=${encodeURIComponent(clip.updated_at)}` : null} alt={clip.title} className="aspect-video rounded-md">
            <button className="absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition hover:bg-black/40 hover:opacity-100" onClick={() => actions.onPreview(clip)} aria-label="Preview clip">
              <Play className="h-7 w-7 text-white drop-shadow" fill="currentColor" />
            </button>
            <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1 font-mono text-[10px] text-ink-50">{fmtDur(clip.duration)}</span>
            <span className="absolute left-1 top-1 rounded bg-black/70 px-1 font-mono text-[10px] text-ink-100">#{clip.rank || '–'}</span>
          </Thumb>
          <label className="absolute -left-1 -top-1 flex h-5 w-5 cursor-pointer items-center justify-center rounded border border-ink-500 bg-ink-850" title="Select for batch actions">
            <input type="checkbox" className="accent-amber-500" checked={selected} onChange={(e) => onSelect(e.target.checked)} />
          </label>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <h4 className="line-clamp-2 text-[13px] font-semibold leading-snug text-ink-50" title={clip.title}>
                {clip.title}
              </h4>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-2xs text-ink-300">
                <button className="font-mono hover:text-amber-400" onClick={() => onSeek?.(clip.start)} title="Seek source preview">
                  {fmtTime(clip.start)} → {fmtTime(clip.end)}
                </button>
                <span>·</span>
                <span>target {clip.target_duration}s</span>
                <Badge>{titleCase(clip.category)}</Badge>
                <StatusBadge status={clip.status} />
                {clip.export_status && <Badge tone={clip.export_status === 'completed' ? 'green' : clip.export_status === 'failed' ? 'red' : 'amber'}>export {clip.export_status}</Badge>}
                {clip.edited && <Badge tone="violet">edited</Badge>}
                {clip.parent_id && <Badge>alternate</Badge>}
              </div>
            </div>
            <ScoreRing score={clip.score} />
          </div>
          {!clip.fits_duration && (
            <div className="mt-1.5 flex items-center gap-1 text-2xs text-amber-300">
              <AlertTriangle className="h-3 w-3" /> Doesn’t fit the {clip.target_duration}s target within tolerance — best available moment.
            </div>
          )}
          {clip.hook && <p className="mt-1.5 line-clamp-2 text-xs italic leading-snug text-ink-100">“{clip.hook}”</p>}
          {clip.tags.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {clip.tags.map((t) => (
                <Badge key={t} tone="amber">
                  {TAG_LABELS[t] ?? titleCase(t)}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="px-3 pb-2">
        <button className="flex w-full items-center gap-1 text-2xs font-medium text-ink-300 hover:text-ink-100" onClick={() => setOpen((v) => !v)}>
          <ChevronDown className={cx('h-3 w-3 transition-transform', open && 'rotate-180')} /> Why this clip · score breakdown
        </button>
        <AnimatePresence initial={false}>
          {open && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.15 }} className="overflow-hidden">
              <div className="mt-2 space-y-2.5 rounded-md border border-ink-600 bg-ink-850 p-2.5">
                {clip.description && <p className="text-2xs leading-relaxed text-ink-200">{clip.description}</p>}
                {clip.reason && (
                  <p className="text-2xs leading-relaxed text-ink-100">
                    <span className="font-semibold text-amber-300">Reason: </span>
                    {clip.reason}
                  </p>
                )}
                <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                  {SCORE_DIMENSIONS.filter((d) => clip.scores[d] !== undefined).map((d) => (
                    <ScoreBar key={d} label={DIM_LABELS[d] ?? d} value={clip.scores[d]} explanation={explanationFor(clip, d)} />
                  ))}
                  {Object.keys(clip.scores)
                    .filter((k) => !k.startsWith('_') && !(SCORE_DIMENSIONS as readonly string[]).includes(k))
                    .map((k) => (
                      <ScoreBar key={k} label={titleCase(k)} value={Number(clip.scores[k]) || 0} explanation={explanationFor(clip, k)} />
                    ))}
                </div>
                <div className="text-[10px] text-ink-400">Source: {clip.analysis_source}</div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      <div className="mt-auto flex items-center gap-1 border-t border-ink-600 bg-ink-850 px-2 py-1.5">
        <Button size="xs" variant="ghost" icon={<Play className="h-3 w-3" />} onClick={() => actions.onPreview(clip)}>
          Preview
        </Button>
        <Link to={`/editor/${clip.id}`}>
          <Button size="xs" variant="subtle" icon={<Pencil className="h-3 w-3" />}>
            Edit
          </Button>
        </Link>
        <div className="mx-1 h-4 w-px bg-ink-600" />
        <IconButton title={clip.status === 'accepted' ? 'Accepted — click to reset' : 'Accept'} active={clip.status === 'accepted'} onClick={() => actions.onStatus(clip, clip.status === 'accepted' ? 'suggested' : 'accepted')}>
          <Check className="h-3.5 w-3.5" />
        </IconButton>
        <IconButton title={clip.status === 'rejected' ? 'Rejected — click to reset' : 'Reject'} className={clip.status === 'rejected' ? 'bg-red-500/15 text-red-300' : ''} onClick={() => actions.onStatus(clip, clip.status === 'rejected' ? 'suggested' : 'rejected')}>
          <X className="h-3.5 w-3.5" />
        </IconButton>
        <IconButton title="Regenerate boundaries" disabled={busy !== null} onClick={() => run('regen', () => actions.onRegenerate(clip))}>
          <RefreshCw className={cx('h-3.5 w-3.5', busy === 'regen' && 'animate-spin')} />
        </IconButton>
        <IconButton title="Duplicate as alternate" disabled={busy !== null} onClick={() => run('dup', () => actions.onDuplicate(clip))}>
          <Copy className="h-3.5 w-3.5" />
        </IconButton>
        <div className="flex-1" />
        <Button size="xs" variant="ghost" icon={<Download className="h-3 w-3" />} onClick={() => actions.onExport(clip)}>
          Export
        </Button>
      </div>
    </div>
  );
}

function explanationFor(c: Clip, key: string): string | undefined {
  const v = c.explanations?.[key];
  if (v === undefined || v === null) return undefined;
  if (typeof v === 'string') return v;
  if (Array.isArray(v)) return v.map(String).join('; ');
  return JSON.stringify(v);
}

/** Plays the source media restricted to [start, end]. */
export function ClipPreviewModal({ clip, onClose }: { clip: Clip | null; onClose: () => void }) {
  const ref = useRef<HTMLVideoElement>(null);
  const [t, setT] = useState(0);
  const [ended, setEnded] = useState(false);
  useEffect(() => {
    setEnded(false);
  }, [clip?.id]);
  const onLoaded = () => {
    const v = ref.current;
    if (!v || !clip) return;
    v.currentTime = clip.start;
    void v.play().catch(() => undefined);
  };
  const onTime = () => {
    const v = ref.current;
    if (!v || !clip) return;
    setT(v.currentTime);
    if (v.currentTime >= clip.end) {
      v.pause();
      v.currentTime = clip.end;
      setEnded(true);
    } else if (v.currentTime < clip.start - 0.5) {
      v.currentTime = clip.start;
    }
  };
  const replay = () => {
    const v = ref.current;
    if (!v || !clip) return;
    v.currentTime = clip.start;
    setEnded(false);
    void v.play();
  };
  return (
    <Modal open={!!clip} onClose={onClose} title={clip?.title ?? ''} width={920}>
      {clip && (
        <div>
          <video
            ref={ref}
            src={apiUrl(`/api/projects/${clip.project_id}/media/stream#t=${clip.start}`)}
            className="aspect-video w-full rounded bg-black"
            controls
            preload="auto"
            onLoadedMetadata={onLoaded}
            onTimeUpdate={onTime}
            onSeeking={() => setEnded(false)}
          />
          <div className="mt-2 flex items-center gap-3">
            <div className="relative h-1.5 flex-1 cursor-pointer rounded-full bg-ink-650" onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              const f = (e.clientX - r.left) / r.width;
              if (ref.current) ref.current.currentTime = clip.start + f * (clip.end - clip.start);
            }}>
              <div className="h-full rounded-full bg-amber-500" style={{ width: `${Math.max(0, Math.min(1, (t - clip.start) / Math.max(0.1, clip.end - clip.start))) * 100}%` }} />
            </div>
            <span className="font-mono text-2xs text-ink-200">
              {fmtTime(Math.max(0, t - clip.start))} / {fmtTime(clip.end - clip.start)}
            </span>
            {ended && (
              <Button size="xs" variant="primary" onClick={replay}>
                Replay
              </Button>
            )}
            <Link to={`/editor/${clip.id}`}>
              <Button size="xs" variant="subtle" icon={<Pencil className="h-3 w-3" />}>
                Open in editor
              </Button>
            </Link>
          </div>
          <div className="mt-2 text-2xs text-ink-300">Raw source range preview (before cuts, reframing and captions). Use the editor for the final look.</div>
        </div>
      )}
    </Modal>
  );
}
