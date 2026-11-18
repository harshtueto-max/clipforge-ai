import { Ban, Download, FolderOpen, Play, RotateCcw, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { api, apiUrl, errMsg } from '../api';
import { fmtBytes, fmtDate, fmtDur } from '../lib/format';
import { toast } from '../stores/toast';
import type { ExportItem, Job } from '../types';
import { Badge, Button, ConfirmDialog, IconButton, Modal, ProgressBar, StatusBadge, Toggle } from './ui';

export function ExportRow({ ex, job, onChanged, showClip = true }: { ex: ExportItem; job?: Job; onChanged?: () => void; showClip?: boolean }) {
  const [playing, setPlaying] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  const [delFile, setDelFile] = useState(false);
  const status = job && (job.status === 'running' || job.status === 'queued') ? job.status : ex.status;
  const progress = job ? job.progress : ex.progress;
  const active = status === 'queued' || status === 'running';
  const p = ex.probe || {};
  const s = ex.settings || {};
  const act = async (fn: () => Promise<unknown>, okMsg?: string) => {
    try {
      await fn();
      if (okMsg) toast.success(okMsg);
      onChanged?.();
    } catch (e) {
      toast.error('Action failed', errMsg(e));
    }
  };
  return (
    <div className="rounded-md border border-ink-600 bg-ink-850 p-2.5">
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {showClip && <span className="truncate text-xs font-medium text-ink-50">{ex.clip_title || 'Untitled clip'}</span>}
            <StatusBadge status={status} />
            {p.validated && <Badge tone="green" title="Output verified with FFprobe">verified</Badge>}
          </div>
          <div className="mt-0.5 truncate text-2xs text-ink-300">
            {[s.resolution, s.fps ? `${s.fps} fps` : null, s.codec, s.quality, s.captions === false ? 'no captions' : null].filter(Boolean).join(' · ')} · {fmtDate(ex.created_at)}
          </div>
        </div>
        <div className="flex items-center gap-0.5">
          {ex.status === 'completed' && (
            <>
              <IconButton title="Play" onClick={() => setPlaying(true)}>
                <Play className="h-3.5 w-3.5" />
              </IconButton>
              <a href={apiUrl(`/api/exports/${ex.id}/file?download=true`)} download>
                <IconButton title="Download">
                  <Download className="h-3.5 w-3.5" />
                </IconButton>
              </a>
              <IconButton title="Show in folder" onClick={() => act(() => api.revealExport(ex.id))}>
                <FolderOpen className="h-3.5 w-3.5" />
              </IconButton>
            </>
          )}
          {active && (
            <Button size="xs" variant="ghost" icon={<Ban className="h-3 w-3" />} onClick={() => act(() => api.cancelExport(ex.id), 'Cancellation requested')}>
              Cancel
            </Button>
          )}
          {(ex.status === 'failed' || ex.status === 'cancelled' || ex.status === 'interrupted') && !active && (
            <Button size="xs" variant="subtle" icon={<RotateCcw className="h-3 w-3" />} onClick={() => act(() => api.retryExport(ex.id), 'Export re-queued')}>
              Retry
            </Button>
          )}
          {!active && (
            <IconButton title="Delete export record" onClick={() => setConfirmDel(true)}>
              <Trash2 className="h-3.5 w-3.5" />
            </IconButton>
          )}
        </div>
      </div>
      {active && (
        <div className="mt-2">
          <ProgressBar value={progress} indeterminate={status === 'queued'} />
          <div className="mt-1 flex justify-between text-2xs text-ink-300">
            <span className="truncate">{job?.message ?? (status === 'queued' ? 'Waiting in render queue' : 'Rendering')}</span>
            <span className="font-mono text-ink-100">{(progress * 100).toFixed(0)}%</span>
          </div>
        </div>
      )}
      {ex.status === 'completed' && (
        <div className="mt-1.5 grid grid-cols-3 gap-x-3 gap-y-0.5 text-2xs text-ink-300">
          <span>
            {p.width}×{p.height}
          </span>
          <span>{fmtDur(p.duration)}</span>
          <span>{fmtBytes(p.size_bytes)}</span>
          <span>video: {p.video_codec ?? '—'}</span>
          <span>audio: {p.audio_codec ?? '—'}</span>
          {p.encoder ? <span>enc: {String(p.encoder)}</span> : <span />}
          {ex.output_path && (
            <span className="col-span-3 truncate font-mono text-[10px] text-ink-400" title={ex.output_path}>
              {ex.output_path}
            </span>
          )}
        </div>
      )}
      {ex.error && <div className="mt-1.5 line-clamp-3 break-words text-2xs text-red-300" title={ex.error}>{ex.error}</div>}
      <Modal open={playing} onClose={() => setPlaying(false)} title={ex.clip_title || 'Export preview'} width={p.width && p.height && p.height > p.width ? 460 : 880}>
        {playing && <video src={apiUrl(`/api/exports/${ex.id}/file`)} controls autoPlay className="max-h-[75vh] w-full rounded bg-black" />}
      </Modal>
      <ConfirmDialog
        open={confirmDel}
        onClose={() => setConfirmDel(false)}
        title="Delete export"
        message="Remove this export from the history?"
        confirmLabel="Delete"
        danger
        onConfirm={() => act(() => api.deleteExport(ex.id, delFile), 'Export deleted')}
      >
        {ex.output_path && <Toggle checked={delFile} onChange={setDelFile} label="Also delete the video file from disk" />}
      </ConfirmDialog>
    </div>
  );
}
