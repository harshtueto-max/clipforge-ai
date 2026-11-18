import { ArrowLeft, AudioLines, Captions as CaptionsIcon, Crop, Download, Info, Layers, Radio } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { Thumb } from '../components/Thumb';
import { ErrorState, LoadingBlock, StatusBadge } from '../components/ui';
import { cx, fmtDur, scoreColor } from '../lib/format';
import { useFetch, useWsEvent } from '../lib/hooks';
import { toast } from '../stores/toast';
import { AudioPanel, ExportPanel } from './AudioExportPanels';
import { CaptionsPanel } from './CaptionsPanel';
import { ClipPanel, FormatPanel, PresetPanel } from './panels';
import { player } from './player';
import { Preview } from './Preview';
import { useEditor } from './store';
import { deleteSelectedSegment, restoreSelectedCut, SaveIndicator, splitAtPlayhead, Timeline } from './Timeline';

const TABS = [
  { id: 'clip', label: 'Clip', icon: Info },
  { id: 'format', label: 'Format', icon: Crop },
  { id: 'captions', label: 'Captions', icon: CaptionsIcon },
  { id: 'audio', label: 'Audio', icon: AudioLines },
  { id: 'preset', label: 'Preset', icon: Layers },
  { id: 'export', label: 'Export', icon: Download },
] as const;
type Tab = (typeof TABS)[number]['id'];

export function EditorPage() {
  const { clipId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const fromLive = searchParams.get('live');
  const nav = useNavigate();
  const { load, data, loading, error, saveState, saveError, flush } = useEditor();
  const [tab, setTab] = useState<Tab>('clip');
  const projectId = data?.clip.project_id;
  const siblings = useFetch(() => (projectId ? api.projectClips(projectId, { sort: 'score' }) : Promise.resolve([])), [projectId]);

  useEffect(() => {
    void load(clipId);
  }, [clipId, load]);

  useEffect(
    () => () => {
      player.pause();
      void useEditor.getState().flush();
    },
    [],
  );

  useWsEvent((m) => {
    if (m.type === 'clips' && m.data.project_id === projectId) void siblings.reload(true);
  });

  // warn about unsaved edits when closing the tab
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => {
      const st = useEditor.getState();
      if (st.tlDirty || st.capDirty || st.saveState === 'saving') {
        void st.flush();
        e.preventDefault();
      }
    };
    window.addEventListener('beforeunload', h);
    return () => window.removeEventListener('beforeunload', h);
  }, []);

  // keyboard shortcuts
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement;
      if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.tagName === 'SELECT' || tgt.isContentEditable)) return;
      const st = useEditor.getState();
      const fps = st.data?.media?.fps || 30;
      const mod = e.ctrlKey || e.metaKey;
      if (e.code === 'Space') {
        e.preventDefault();
        player.toggle();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        player.step(e.shiftKey ? -1 : -1 / fps);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        player.step(e.shiftKey ? 1 : 1 / fps);
      } else if (mod && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (e.shiftKey) st.redo();
        else st.undo();
      } else if (mod && e.key.toLowerCase() === 'y') {
        e.preventDefault();
        st.redo();
      } else if (mod && e.key.toLowerCase() === 's') {
        e.preventDefault();
        void st.flush();
      } else if (!mod && e.key.toLowerCase() === 's') {
        splitAtPlayhead();
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        if (st.selSegment) {
          e.preventDefault();
          const err = deleteSelectedSegment();
          if (err) toast.warning(err);
        } else if (st.selCut !== null && e.shiftKey) {
          restoreSelectedCut();
        }
      } else if (e.key === 'Home') {
        if (st.timeline) player.seek(st.timeline.start);
      } else if (e.key === 'End') {
        if (st.timeline) player.seek(st.timeline.end - 0.05);
      }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);

  const goClip = async (id: string) => {
    if (id === clipId) return;
    await flush();
    nav(`/editor/${id}`);
  };

  if (error)
    return (
      <div className="p-6">
        <ErrorState message={error} onRetry={() => load(clipId)} />
      </div>
    );
  if (loading || !data) return <LoadingBlock label="Loading editor…" />;

  return (
    <div className="flex h-full min-h-0">
      {/* clip list */}
      <aside className="flex w-[220px] shrink-0 flex-col border-r border-ink-600 bg-ink-850">
        <div className="flex h-10 items-center gap-2 border-b border-ink-600 px-2">
          {fromLive || data.clip.tags.includes('live_manual') || data.clip.tags.includes('live_ai') ? (
            <Link to="/live" className="flex items-center gap-1 text-2xs font-semibold text-red-300 hover:text-red-200" onClick={() => void flush()}>
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" /> <Radio className="h-3 w-3" aria-hidden="true" /> Live Stream
            </Link>
          ) : (
            <Link to={`/projects/${data.clip.project_id}`} className="flex items-center gap-1 text-2xs text-ink-300 hover:text-ink-50" onClick={() => void flush()}>
              <ArrowLeft className="h-3.5 w-3.5" /> Project
            </Link>
          )}
          <span className="ml-auto text-2xs text-ink-400">{siblings.data?.length ?? 0} clips</span>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
          {(siblings.data ?? []).map((c) => (
            <button
              key={c.id}
              onClick={() => goClip(c.id)}
              className={cx('mb-1 flex w-full gap-2 rounded-md border p-1.5 text-left transition-colors', c.id === clipId ? 'border-amber-500/60 bg-amber-500/5' : 'border-transparent hover:bg-ink-750')}
            >
              <Thumb src={c.has_thumbnail ? `/api/clips/${c.id}/thumbnail` : null} alt="" className="h-10 w-16 shrink-0 rounded" iconSize="h-4 w-4" />
              <div className="min-w-0 flex-1">
                <div className="line-clamp-2 text-[11px] leading-tight text-ink-100">{c.title}</div>
                <div className="mt-0.5 flex items-center gap-1 text-[10px] text-ink-400">
                  <span className="font-mono font-semibold" style={{ color: scoreColor(c.score) }}>
                    {c.score.toFixed(0)}
                  </span>
                  <span>{fmtDur(c.duration)}</span>
                  {c.status !== 'suggested' && <StatusBadge status={c.status} />}
                </div>
              </div>
            </button>
          ))}
        </div>
      </aside>

      {/* center */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-10 shrink-0 items-center gap-2 border-b border-ink-600 bg-ink-850 px-3">
          <h2 className="min-w-0 truncate text-xs font-semibold text-ink-50">{data.clip.title}</h2>
          <span className="shrink-0 text-2xs text-ink-400">{data.clip.project_name ?? ''}</span>
          <div className="flex-1" />
          <SaveIndicator state={saveState} error={saveError} />
        </div>
        <div className="min-h-0 flex-1">
          <Preview />
        </div>
        <div className="h-[268px] shrink-0">
          <Timeline onOpenTab={(t) => setTab(t as Tab)} />
        </div>
      </div>

      {/* right panel */}
      <aside className="flex w-[340px] shrink-0 flex-col border-l border-ink-600 bg-ink-800">
        <div className="grid shrink-0 grid-cols-6 border-b border-ink-600">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              title={t.label}
              className={cx('flex h-12 flex-col items-center justify-center gap-0.5 text-[10px] font-medium transition-colors', tab === t.id ? 'bg-ink-700 text-amber-400 shadow-[inset_0_-2px_0_0_#ffab1a]' : 'text-ink-300 hover:text-ink-50')}
            >
              <t.icon className="h-4 w-4" />
              {t.label}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {tab === 'clip' && <ClipPanel />}
          {tab === 'format' && <FormatPanel />}
          {tab === 'captions' && <CaptionsPanel />}
          {tab === 'audio' && <AudioPanel />}
          {tab === 'preset' && <PresetPanel />}
          {tab === 'export' && <ExportPanel />}
        </div>
      </aside>
    </div>
  );
}
