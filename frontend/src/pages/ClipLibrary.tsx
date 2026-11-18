import { Download, Film, Pencil, Play, Search } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { ClipPreviewModal } from '../components/ClipCard';
import { ExportDialog } from '../components/ExportDialog';
import { PageHeader } from '../components/PageHeader';
import { Thumb } from '../components/Thumb';
import { Badge, Button, EmptyState, ErrorState, Field, inputCls, LoadingBlock, ScoreRing, Select, Slider, StatusBadge } from '../components/ui';
import { fmtDur, fmtTime, titleCase } from '../lib/format';
import { useFetch, useWsEvent } from '../lib/hooks';
import type { Clip } from '../types';
import { CATEGORIES, TAG_LABELS } from '../types';

export function ClipLibraryPage() {
  const [status, setStatus] = useState('all');
  const [category, setCategory] = useState('all');
  const [minScore, setMinScore] = useState(0);
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<'score' | 'recent'>('score');
  const [preview, setPreview] = useState<Clip | null>(null);
  const [exportIds, setExportIds] = useState<string[] | null>(null);
  const clips = useFetch(
    () => api.clips({ status: status === 'all' ? undefined : status, category: category === 'all' ? undefined : category, min_score: minScore || undefined, q: query || undefined, sort }),
    [status, category, minScore, query, sort],
  );
  useWsEvent((m) => {
    if (m.type === 'clips' || m.type === 'export') void clips.reload(true);
  });
  return (
    <div>
      <PageHeader title="Clip Library" subtitle="Every discovered clip across all projects.">
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <Field label="Search title / transcript" className="w-64">
            <div className="relative">
              <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-ink-400" />
              <input className={`${inputCls} pl-8`} value={q} placeholder="Press Enter to search" onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && setQuery(q.trim())} onBlur={() => setQuery(q.trim())} />
            </div>
          </Field>
          <Field label="Status" className="w-32">
            <Select value={status} onChange={setStatus} options={[{ value: 'all', label: 'All' }, { value: 'suggested', label: 'Suggested' }, { value: 'accepted', label: 'Accepted' }, { value: 'rejected', label: 'Rejected' }]} />
          </Field>
          <Field label="Category" className="w-32">
            <Select value={category} onChange={setCategory} options={[{ value: 'all', label: 'All' }, ...CATEGORIES.map((c) => ({ value: c, label: titleCase(c) }))]} />
          </Field>
          <div className="w-40">
            <Slider label="Min score" value={minScore} min={0} max={95} step={5} onChange={setMinScore} />
          </div>
          <Field label="Sort" className="w-32">
            <Select value={sort} onChange={setSort} options={[{ value: 'score', label: 'Score' }, { value: 'recent', label: 'Most recent' }]} />
          </Field>
        </div>
      </PageHeader>
      <div className="p-6">
        {clips.loading && !clips.data ? (
          <LoadingBlock />
        ) : clips.error ? (
          <ErrorState message={clips.error} onRetry={() => clips.reload()} />
        ) : !clips.data?.length ? (
          <EmptyState icon={<Film className="h-7 w-7" />} title="No clips found">
            Analyze a project to discover clips, or relax the filters.
          </EmptyState>
        ) : (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 2xl:grid-cols-3">
            {clips.data.map((c) => (
              <div key={c.id} className="flex gap-3 rounded-lg border border-ink-600 bg-ink-800 p-3">
                <Thumb src={c.has_thumbnail ? `/api/clips/${c.id}/thumbnail` : null} alt={c.title} className="aspect-video w-36 shrink-0 rounded-md">
                  <button className="absolute inset-0 flex items-center justify-center opacity-0 transition hover:bg-black/40 hover:opacity-100" onClick={() => setPreview(c)} aria-label="Preview">
                    <Play className="h-6 w-6 text-white" fill="currentColor" />
                  </button>
                  <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1 font-mono text-[10px]">{fmtDur(c.duration)}</span>
                </Thumb>
                <div className="min-w-0 flex-1">
                  <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="line-clamp-2 text-xs font-semibold text-ink-50">{c.title}</div>
                      <Link to={`/projects/${c.project_id}`} className="text-2xs text-ink-300 hover:text-amber-400">
                        {c.project_name ?? 'Project'}
                      </Link>
                      <span className="ml-1.5 font-mono text-2xs text-ink-400">
                        {fmtTime(c.start)}–{fmtTime(c.end)}
                      </span>
                    </div>
                    <ScoreRing score={c.score} size={36} />
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    <StatusBadge status={c.status} />
                    <Badge>{titleCase(c.category)}</Badge>
                    {c.export_status && <Badge tone={c.export_status === 'completed' ? 'green' : 'amber'}>export {c.export_status}</Badge>}
                    {c.tags.slice(0, 2).map((t) => (
                      <Badge key={t} tone="amber">
                        {TAG_LABELS[t] ?? t}
                      </Badge>
                    ))}
                  </div>
                  <div className="mt-2 flex gap-1">
                    <Link to={`/editor/${c.id}`}>
                      <Button size="xs" variant="subtle" icon={<Pencil className="h-3 w-3" />}>
                        Open in editor
                      </Button>
                    </Link>
                    <Button size="xs" variant="ghost" icon={<Download className="h-3 w-3" />} onClick={() => setExportIds([c.id])}>
                      Export
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <ClipPreviewModal clip={preview} onClose={() => setPreview(null)} />
      <ExportDialog open={!!exportIds} clipIds={exportIds ?? []} onClose={() => setExportIds(null)} onQueued={() => clips.reload(true)} />
    </div>
  );
}
