import { BarChart3, CheckCheck, Download, Film, FileText, Play, RefreshCw, ScanSearch, Trash2, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { api, ApiError, apiUrl, errMsg } from '../api';
import { AnalysisOptions, defaultAnalysisOptions, toAnalyzeParams, type AnalysisOptionsValue } from '../components/AnalysisOptions';
import { ClipCard, ClipPreviewModal, type ClipActions } from '../components/ClipCard';
import { ExportDialog } from '../components/ExportDialog';
import { JobRow } from '../components/JobRow';
import { PageHeader } from '../components/PageHeader';
import { AnalysisSummaryView, SourceInfo } from '../components/ProjectInfo';
import { TranscriptView } from '../components/TranscriptView';
import { Button, ConfirmDialog, EmptyState, ErrorState, Field, LoadingBlock, Modal, Panel, Select, Slider, StatusBadge, Toggle } from '../components/ui';
import { cx, titleCase } from '../lib/format';
import { useFetch, useWsEvent } from '../lib/hooks';
import { useJobs } from '../stores/jobs';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import type { Clip } from '../types';
import { CATEGORIES, DIM_LABELS, SCORE_DIMENSIONS } from '../types';

const RANKINGS = [
  { id: 'all', label: 'All clips' },
  { id: 'best_overall', label: 'Best Overall' },
  { id: 'highest_hook', label: 'Highest Hook' },
  { id: 'best_story', label: 'Best Story' },
  { id: 'most_informative', label: 'Most Informative' },
  { id: 'funniest', label: 'Funniest' },
  { id: 'most_emotional', label: 'Most Emotional' },
  { id: 'best_standalone', label: 'Best Standalone' },
] as const;
type Ranking = (typeof RANKINGS)[number]['id'];

const SORTS = [
  { value: 'score', label: 'Score' },
  { value: 'hook', label: 'Hook' },
  { value: 'story', label: 'Story' },
  { value: 'information', label: 'Information' },
  { value: 'emotion', label: 'Emotion' },
  { value: 'standalone', label: 'Standalone' },
  { value: 'timeline', label: 'Timeline position' },
  { value: 'duration', label: 'Duration' },
];

function rankValue(c: Clip, r: string): number {
  switch (r) {
    case 'highest_hook':
    case 'hook':
      return c.scores.hook ?? 0;
    case 'best_story':
    case 'story':
      return c.scores.story ?? 0;
    case 'most_informative':
    case 'information':
      return c.scores.information ?? 0;
    case 'most_emotional':
    case 'emotion':
      return c.scores.emotion ?? 0;
    case 'best_standalone':
    case 'standalone':
      return c.scores.standalone ?? 0;
    case 'funniest':
      return (c.tags.includes('funniest') ? 1000 : 0) + (c.category === 'funny' ? 500 : 0) + c.score;
    case 'timeline':
      return -c.start;
    case 'duration':
      return c.duration;
    default:
      return c.score;
  }
}

export function ProjectPage() {
  const { id = '' } = useParams();
  const project = useFetch(() => api.project(id), [id]);
  const clipsQ = useFetch(() => api.projectClips(id, { sort: 'score' }), [id]);
  const analysis = useFetch(() => api.analysis(id), [id]);
  const jobs = useJobs((s) => s.jobs);
  const { settings, load } = useSettings();
  const [tab, setTab] = useState<'clips' | 'transcript'>('clips');
  const [ranking, setRanking] = useState<Ranking>('all');
  const [sort, setSort] = useState('score');
  const [target, setTarget] = useState<string>('all');
  const [category, setCategory] = useState<string>('all');
  const [speaker, setSpeaker] = useState<string>('all');
  const [status, setStatus] = useState<string>('all');
  const [minScore, setMinScore] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<Clip | null>(null);
  const [exportIds, setExportIds] = useState<string[] | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [runModal, setRunModal] = useState<null | 'analyze' | 'rediscover'>(null);
  const [time, setTime] = useState(0);
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (!settings) void load();
  }, [settings, load]);

  useWsEvent((m) => {
    if (m.type === 'project' && m.data.id === id) {
      void project.reload(true);
      if (m.data.status === 'analyzed') void analysis.reload(true);
    }
    if (m.type === 'clips' && m.data.project_id === id) void clipsQ.reload(true);
    if (m.type === 'job' && m.data.project_id === id && ['completed', 'failed'].includes(m.data.status)) {
      void project.reload(true);
      if (m.data.kind === 'render') void clipsQ.reload(true);
    }
  });

  const projectJobs = Object.values(jobs)
    .filter((j) => j.project_id === id)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  const activeJobs = projectJobs.filter((j) => (j.status === 'running' || j.status === 'queued') && j.kind !== 'render');
  const lastPipeline = projectJobs.find((j) => j.kind !== 'render' && j.kind !== 'proxy');
  const lastFailed = lastPipeline && ['failed', 'interrupted'].includes(lastPipeline.status) ? lastPipeline : undefined;
  const pipelineBusy = activeJobs.some((j) => ['analysis', 'rediscover', 'import', 'download'].includes(j.kind));

  const clips = useMemo(() => clipsQ.data ?? [], [clipsQ.data]);
  const targets = useMemo(() => [...new Set(clips.map((c) => c.target_duration))].sort((a, b) => a - b), [clips]);
  const speakers = useMemo(() => [...new Set(clips.flatMap((c) => c.speakers))].sort((a, b) => a - b), [clips]);
  const shown = useMemo(() => {
    let list = clips.filter(
      (c) =>
        (target === 'all' || c.target_duration === Number(target)) &&
        (category === 'all' || c.category === category) &&
        (speaker === 'all' || c.speakers.includes(Number(speaker))) &&
        (status === 'all' || c.status === status) &&
        c.score >= minScore,
    );
    const key = ranking === 'all' ? sort : ranking;
    list = [...list].sort((a, b) => rankValue(b, key) - rankValue(a, key));
    return list;
  }, [clips, target, category, speaker, status, minScore, ranking, sort]);

  const replaceClip = (c: Clip) => clipsQ.setData((prev) => (prev ? prev.map((x) => (x.id === c.id ? { ...x, ...c, project_name: x.project_name } : x)) : prev));
  const seek = (t: number) => {
    if (video.current) {
      video.current.currentTime = t;
      void video.current.play().catch(() => undefined);
    }
  };

  const actions: ClipActions = {
    onPreview: setPreview,
    onStatus: async (c, s) => {
      try {
        replaceClip(await api.updateClip(c.id, { status: s }));
      } catch (e) {
        toast.error('Could not update clip', errMsg(e));
      }
    },
    onRegenerate: async (c) => {
      try {
        replaceClip(await api.regenerate(c.id));
        toast.success('Clip regenerated', 'New boundaries were found and the auto-edit was rebuilt.');
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) toast.warning('No alternative found', e.message);
        else toast.error('Regenerate failed', errMsg(e));
      }
    },
    onDuplicate: async (c) => {
      try {
        const n = await api.duplicate(c.id);
        clipsQ.setData((prev) => (prev ? [...prev, n] : [n]));
        toast.success('Alternate created', n.title);
      } catch (e) {
        toast.error('Duplicate failed', errMsg(e));
      }
    },
    onExport: (c) => setExportIds([c.id]),
  };

  const batch = async (action: 'accept' | 'reject' | 'delete') => {
    const ids = [...selected];
    try {
      const r = await api.batch(ids, action);
      toast.success(`${r.updated} clip(s) ${action === 'delete' ? 'deleted' : `${action}ed`}`);
      setSelected(new Set());
      await clipsQ.reload(true);
    } catch (e) {
      toast.error('Batch action failed', errMsg(e));
    }
  };

  if (project.loading && !project.data) return <LoadingBlock label="Loading project…" />;
  if (project.error || !project.data)
    return (
      <div className="p-6">
        <ErrorState message={project.error ?? 'Project not found'} onRetry={() => project.reload()} />
      </div>
    );
  const p = project.data;
  const analyzed = !!p.analysis_summary?.stages?.transcribe;

  return (
    <div className="flex min-h-full flex-col">
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            {p.name} <StatusBadge status={p.status} />
          </span>
        }
        subtitle={`${p.clip_count} clips · ${p.accepted_count} accepted · ${p.export_count} exports`}
        actions={
          <>
            {analyzed && (
              <Button variant="secondary" icon={<RefreshCw className="h-3.5 w-3.5" />} disabled={pipelineBusy} onClick={() => setRunModal('rediscover')}>
                Re-discover
              </Button>
            )}
            <Button variant="primary" icon={<ScanSearch className="h-3.5 w-3.5" />} disabled={pipelineBusy || !p.media} onClick={() => setRunModal('analyze')}>
              {analyzed ? 'Re-analyze' : 'Analyze'}
            </Button>
          </>
        }
      >
        {(activeJobs.length > 0 || lastFailed) && (
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {activeJobs.map((j) => (
              <JobRow key={j.id} job={j} />
            ))}
            {!pipelineBusy && lastFailed && <JobRow job={lastFailed} />}
          </div>
        )}
      </PageHeader>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 p-4 xl:grid-cols-[1fr_400px]">
        <div className="flex min-w-0 flex-col rounded-lg border border-ink-600 bg-ink-800">
          <div className="flex h-10 items-center gap-1 border-b border-ink-600 px-2">
            <TabBtn active={tab === 'clips'} onClick={() => setTab('clips')} icon={<Film className="h-3.5 w-3.5" />}>
              Clips <span className="text-ink-300">{clips.length}</span>
            </TabBtn>
            <TabBtn active={tab === 'transcript'} onClick={() => setTab('transcript')} icon={<FileText className="h-3.5 w-3.5" />}>
              Transcript
            </TabBtn>
          </div>
          {tab === 'transcript' ? (
            <div className="h-[calc(100vh-260px)] min-h-[400px]">
              <TranscriptView projectId={id} currentTime={time} onSeek={seek} />
            </div>
          ) : (
            <div className="flex min-h-0 flex-col">
              <div className="flex flex-wrap gap-1 border-b border-ink-600 px-3 py-2">
                {RANKINGS.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => setRanking(r.id)}
                    className={cx('h-6 rounded px-2 text-2xs font-medium transition-colors', ranking === r.id ? 'bg-amber-500/15 text-amber-300' : 'text-ink-200 hover:bg-ink-700 hover:text-ink-50')}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap items-end gap-3 border-b border-ink-600 px-3 py-2">
                <Field label="Duration" className="w-28">
                  <Select value={target} onChange={setTarget} options={[{ value: 'all', label: 'All' }, ...targets.map((t) => ({ value: String(t), label: `${t}s` }))]} />
                </Field>
                <Field label="Category" className="w-32">
                  <Select value={category} onChange={setCategory} options={[{ value: 'all', label: 'All' }, ...CATEGORIES.map((c) => ({ value: c, label: titleCase(c) }))]} />
                </Field>
                <Field label="Speaker" className="w-24">
                  <Select value={speaker} onChange={setSpeaker} options={[{ value: 'all', label: 'All' }, ...speakers.map((s) => ({ value: String(s), label: `S${s + 1}` }))]} />
                </Field>
                <Field label="Status" className="w-28">
                  <Select value={status} onChange={setStatus} options={[{ value: 'all', label: 'All' }, { value: 'suggested', label: 'Suggested' }, { value: 'accepted', label: 'Accepted' }, { value: 'rejected', label: 'Rejected' }]} />
                </Field>
                <div className="w-36">
                  <Slider label="Min score" value={minScore} min={0} max={95} step={5} onChange={setMinScore} />
                </div>
                <Field label="Sort by" className="w-40">
                  <Select value={sort} onChange={setSort} options={SORTS} disabled={ranking !== 'all'} />
                </Field>
                <span className="pb-2 text-2xs text-ink-300">{shown.length} shown</span>
              </div>
              {selected.size > 0 && (
                <div className="flex items-center gap-2 border-b border-amber-500/30 bg-amber-500/5 px-3 py-1.5 text-xs">
                  <span className="font-medium text-amber-300">{selected.size} selected</span>
                  <Button size="xs" variant="subtle" icon={<CheckCheck className="h-3 w-3" />} onClick={() => batch('accept')}>
                    Accept
                  </Button>
                  <Button size="xs" variant="subtle" icon={<X className="h-3 w-3" />} onClick={() => batch('reject')}>
                    Reject
                  </Button>
                  <Button size="xs" variant="subtle" icon={<Download className="h-3 w-3" />} onClick={() => setExportIds([...selected])}>
                    Export
                  </Button>
                  <Button size="xs" variant="danger" icon={<Trash2 className="h-3 w-3" />} onClick={() => setConfirmDelete(true)}>
                    Delete
                  </Button>
                  <div className="flex-1" />
                  <button className="text-2xs text-ink-300 hover:text-ink-50" onClick={() => setSelected(new Set(shown.map((c) => c.id)))}>
                    Select all shown
                  </button>
                  <button className="text-2xs text-ink-300 hover:text-ink-50" onClick={() => setSelected(new Set())}>
                    Clear
                  </button>
                </div>
              )}
              <div className="p-3">
                {clipsQ.loading && !clipsQ.data ? (
                  <LoadingBlock label="Loading clips…" />
                ) : clipsQ.error ? (
                  <ErrorState message={clipsQ.error} onRetry={() => clipsQ.reload()} />
                ) : clips.length === 0 ? (
                  <EmptyState icon={<BarChart3 className="h-7 w-7" />} title={pipelineBusy ? 'Analysis in progress…' : 'No clips yet'}>
                    {pipelineBusy ? 'Clips appear here as soon as discovery finishes.' : p.media ? 'Run the analysis to discover the best moments.' : 'Import a video first.'}
                  </EmptyState>
                ) : shown.length === 0 ? (
                  <EmptyState title="No clips match the filters" />
                ) : (
                  <div className="grid grid-cols-1 gap-3 2xl:grid-cols-2">
                    {shown.map((c) => (
                      <ClipCard
                        key={c.id}
                        clip={c}
                        selected={selected.has(c.id)}
                        onSelect={(v) =>
                          setSelected((prev) => {
                            const n = new Set(prev);
                            if (v) n.add(c.id);
                            else n.delete(c.id);
                            return n;
                          })
                        }
                        actions={actions}
                        onSeek={seek}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-4">
          <Panel title="Source preview" bodyClass="p-0">
            {p.media ? (
              <video
                ref={video}
                key={`${p.media.id}-${p.media.proxy_ready}`}
                src={apiUrl(`/api/projects/${id}/media/stream`)}
                controls
                preload="metadata"
                className="aspect-video w-full bg-black"
                onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
              />
            ) : (
              <div className="flex aspect-video items-center justify-center bg-ink-950 text-xs text-ink-300">
                <Play className="mr-2 h-4 w-4" /> No media yet
              </div>
            )}
          </Panel>
          <Panel title="Source info">
            <SourceInfo project={p} />
          </Panel>
          <Panel title="Analysis summary">
            <AnalysisSummaryView project={p} analysis={analysis.data} />
          </Panel>
        </div>
      </div>

      <ClipPreviewModal clip={preview} onClose={() => setPreview(null)} />
      <ExportDialog open={!!exportIds} clipIds={exportIds ?? []} onClose={() => setExportIds(null)} onQueued={() => setSelected(new Set())} />
      <ConfirmDialog open={confirmDelete} onClose={() => setConfirmDelete(false)} title="Delete clips" danger confirmLabel="Delete" message={`Delete ${selected.size} selected clip(s)? Their edits are removed too.`} onConfirm={() => batch('delete')} />
      {runModal && (
        <RunModal
          mode={runModal}
          projectId={id}
          initial={{ ...defaultAnalysisOptions(settings), ...pickOpts(p.options) }}
          weights={(p.options.score_weights as Record<string, number> | undefined) ?? settings?.score_weights ?? {}}
          maxPer={Number(p.options.max_clips_per_target ?? settings?.max_clips_per_target ?? 8)}
          onClose={() => setRunModal(null)}
        />
      )}
    </div>
  );
}

function pickOpts(o: Record<string, unknown>): Partial<AnalysisOptionsValue> {
  const out: Partial<AnalysisOptionsValue> = {};
  if (Array.isArray(o.duration_targets)) out.duration_targets = (o.duration_targets as unknown[]).map(Number);
  if (typeof o.duration_tolerance === 'number') out.duration_tolerance = o.duration_tolerance;
  if (typeof o.whisper_model === 'string') out.whisper_model = o.whisper_model;
  if (typeof o.language === 'string') out.language = o.language;
  if (o.analysis_quality === 'fast' || o.analysis_quality === 'balanced' || o.analysis_quality === 'high') out.analysis_quality = o.analysis_quality;
  if (typeof o.preset_id === 'string') out.preset_id = o.preset_id;
  if (o.aspect === '9:16' || o.aspect === '16:9' || o.aspect === '1:1' || o.aspect === '4:5') out.aspect = o.aspect;
  return out;
}

function TabBtn({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className={cx('flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors', active ? 'bg-ink-700 text-ink-50' : 'text-ink-200 hover:text-ink-50')}>
      {icon}
      {children}
    </button>
  );
}

function RunModal({ mode, projectId, initial, weights, maxPer: maxPer0, onClose }: { mode: 'analyze' | 'rediscover'; projectId: string; initial: AnalysisOptionsValue; weights: Record<string, number>; maxPer: number; onClose: () => void }) {
  const [opts, setOpts] = useState<AnalysisOptionsValue>(initial);
  const [w, setW] = useState<Record<string, number>>({ ...weights });
  const [force, setForce] = useState(false);
  const [maxPer, setMaxPer] = useState<number>(maxPer0);
  const [busy, setBusy] = useState(false);
  const [customWeights, setCustomWeights] = useState(mode === 'rediscover');
  const submit = async () => {
    setBusy(true);
    try {
      const body = { ...toAnalyzeParams(opts), max_clips_per_target: maxPer, ...(customWeights ? { score_weights: w } : {}), ...(mode === 'analyze' ? { force } : {}) };
      if (mode === 'analyze') await api.analyze(projectId, body);
      else await api.rediscover(projectId, body);
      toast.success(mode === 'analyze' ? 'Analysis started' : 'Re-discovery started');
      onClose();
    } catch (e) {
      toast.error('Could not start', errMsg(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={mode === 'analyze' ? 'Analyze video' : 'Re-discover clips'}
      width={720}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} disabled={!opts.duration_targets.length} onClick={submit}>
            {mode === 'analyze' ? 'Start analysis' : 'Re-discover'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {mode === 'rediscover' && (
          <div className="rounded-md border border-ink-600 bg-ink-850 p-2.5 text-2xs text-ink-200">
            Re-discovery reuses the existing transcript and analysis — it only re-scores and re-selects clips (fast). Accepted and edited clips are kept; untouched suggestions are replaced.
          </div>
        )}
        <AnalysisOptions value={opts} onChange={setOpts} showAuto={false} />
        <div className="grid grid-cols-2 gap-4">
          <Slider label="Max clips per target" value={maxPer} min={1} max={30} step={1} onChange={setMaxPer} />
          {mode === 'analyze' && <Toggle checked={force} onChange={setForce} label="Force full re-analysis" hint="Re-run transcription and vision even if cached results exist." />}
        </div>
        <div>
          <Toggle checked={customWeights} onChange={setCustomWeights} label="Score weights for this run" />
          {customWeights && (
            <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
              {SCORE_DIMENSIONS.map((d) => (
                <Slider key={d} label={DIM_LABELS[d]} value={w[d] ?? 0} min={0} max={50} step={1} onChange={(v) => setW({ ...w, [d]: v })} />
              ))}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
