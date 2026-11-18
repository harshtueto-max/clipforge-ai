import { Ban, RotateCcw, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api, errMsg } from '../api';
import { fmtDate } from '../lib/format';
import { KIND_LABELS, STAGE_LABELS, useJobs } from '../stores/jobs';
import { toast } from '../stores/toast';
import type { Job } from '../types';
import { Button, ProgressBar, StatusBadge } from './ui';

export function jobTitle(j: Job): string {
  const base = KIND_LABELS[j.kind] ?? j.kind;
  const p = j.params as Record<string, unknown>;
  if (j.kind === 'model_download' && typeof p.name === 'string') return `${base}: ${p.name}`;
  if (j.kind === 'download' && typeof p.url === 'string') return `${base}`;
  return base;
}

export function JobRow({ job, compact, projectName }: { job: Job; compact?: boolean; projectName?: string }) {
  const remove = useJobs((s) => s.remove);
  const active = job.status === 'queued' || job.status === 'running';
  const failed = job.status === 'failed' || job.status === 'interrupted' || job.status === 'cancelled';
  const cancel = async () => {
    try {
      await api.cancelJob(job.id);
      toast.info('Cancellation requested');
    } catch (e) {
      toast.error('Cancel failed', errMsg(e));
    }
  };
  const retry = async () => {
    try {
      await api.retryJob(job.id);
      toast.success('Job re-queued');
    } catch (e) {
      toast.error('Retry failed', errMsg(e));
    }
  };
  const dismiss = async () => {
    try {
      await api.deleteJob(job.id);
      remove(job.id);
    } catch (e) {
      toast.error('Could not remove job', errMsg(e));
    }
  };
  return (
    <div className="rounded-md border border-ink-600 bg-ink-850 p-2.5">
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-xs font-medium text-ink-50">{jobTitle(job)}</span>
            <StatusBadge status={job.status} />
          </div>
          <div className="mt-0.5 truncate text-2xs text-ink-300">
            {job.project_id ? (
              <Link className="hover:text-amber-400" to={`/projects/${job.project_id}`}>
                {projectName ?? 'Open project'}
              </Link>
            ) : (
              'System'
            )}
            {' · '}
            {fmtDate(job.created_at)}
          </div>
        </div>
        {active && (
          <Button size="xs" variant="ghost" icon={<Ban className="h-3 w-3" />} onClick={cancel}>
            Cancel
          </Button>
        )}
        {failed && (
          <>
            <Button size="xs" variant="subtle" icon={<RotateCcw className="h-3 w-3" />} onClick={retry}>
              {job.status === 'interrupted' ? 'Resume' : 'Retry'}
            </Button>
            {!compact && (
              <Button size="xs" variant="ghost" icon={<Trash2 className="h-3 w-3" />} onClick={dismiss} title="Remove from list" />
            )}
          </>
        )}
      </div>
      {active && (
        <div className="mt-2">
          <ProgressBar value={job.progress} indeterminate={job.status === 'queued'} />
          <div className="mt-1 flex justify-between gap-2 text-2xs text-ink-300">
            <span className="truncate">
              {job.stage ? `${STAGE_LABELS[job.stage] ?? job.stage} · ` : ''}
              {job.message}
            </span>
            <span className="font-mono text-ink-100">{(job.progress * 100).toFixed(0)}%</span>
          </div>
        </div>
      )}
      {job.error && !active && <div className="mt-1.5 line-clamp-3 break-words text-2xs text-red-300" title={job.error}>{job.error}</div>}
      {!active && !job.error && job.message && failed && <div className="mt-1 text-2xs text-ink-300">{job.message}</div>}
    </div>
  );
}
